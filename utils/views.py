from typing import Any, final, overload, TypedDict, NoReturn, Callable
from abc import ABC, abstractmethod

from django.views.generic import View
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden, JsonResponse
from django.core.exceptions import ImproperlyConfigured
from django.template.response import TemplateResponse

from .log import err_capture
from .http import HttpRequest
from .global_messages import wrong


__all__ = [
    'SecureView', 'SecureJsonView', 'SecureTemplateView',
]


class ResponseCreated(Exception):
    '''标识response已经被创建，不再需要继续处理'''
    def __init__(self, response: HttpResponse | None = None) -> None:
        self.response = response



class SecureView(View, ABC):
    """
    通用的视图类基类

    主要功能：权限检查、方法分发、参数检查

    权限检查：
    - 可以根据需要设置perms_required，访问者需要同时具有所有权限才能访问

    方法分发 + 参数检查：
    - 通过`get_method_name`获取`dispatch_prepare`参数名，被`method_names`检查
    - 通过`dispatch_prepare`执行该参数的准备过程，并获取处理函数名
    - `dispatch_prepare`调用`_PrepareFuncType`类型的函数，返回值为方法名
    - 检查存在性后，通过处理函数名调用对应方法处理最终请求，实现业务逻辑
    - 子类可以重载`_dispatch`以强化分发的功能，不建议重载`dispatch`
    """
    # 由View.setup自动设置，在子类修改以提供更多类型提示信息
    request: HttpRequest
    _ArgType = tuple
    args: _ArgType
    _KWType = TypedDict('_KWType', {})
    kwargs: _KWType
    # TODO: 兼容以下新接口，减少函数参数使用
    _PrepareFuncType = Callable[[], str | None]
    _HandlerFuncType = Callable[[], HttpResponse]

    # 视图设置
    login_required: bool = True
    perms_required: list[str] = []
    http_method_names: list[str] = ['get', 'post']
    # get_method_name 的有效返回值，对dispatch_prepare的返回值不做检查
    method_names: list[str] = http_method_names

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        # 设置request, args, kwargs
        super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        '''自动捕获ResponseCreated信号，错误时由error_response处理'''
        # 类型注释继承自父类，无需重写
        try:
            return self._dispatch()
        except ResponseCreated:
            return self.response
        except Exception as e:
            err = e
            try:
                return self.error_response(err)
            except ResponseCreated:
                return self.response
        # 出错时理应不再抛出异常，但以防万一仍然捕获ResponseCreated信号

    def _dispatch(self) -> HttpResponse:
        '''
        实际dispatch函数
        通过response_created产生信号ResponseCreated传递
        暂时兼容正常返回
        '''
        # Check method
        self.check_http()

        # Check permission
        self.check_perm()

        # Decide prepare handler
        method_name = self.get_method_name(self.request)
        if method_name not in self.method_names:
            return self._check_http_method()

        # Prepare and decide final handler
        method_name = self.dispatch_prepare(method_name) or method_name
        if not hasattr(self, method_name):
            raise ImproperlyConfigured(
                f'SecureView requires an implementation of `{method_name}`'
            )
        handler: SecureView._HandlerFuncType = getattr(self, method_name)

        # Handle
        return handler()

    def response_created(self, response: HttpResponse) -> NoReturn:
        '''
        保存生成的Response，并发送ResponseCreated信号

        :param response: 
        :type response: HttpResponse
        :raise ResponseCreated: 不包含信息的信号
        '''
        self.response = response
        raise ResponseCreated()

    def _allow_methods(self):
        '''被http_method_not_allowed调用的方法，仅用于保持提示信息正常'''
        return [m.upper() for m in self.http_method_names]

    def check_http(self) -> None:
        '''
        检查请求是否合法，拦截攻击行为，只使用request
        '''
        self._check_http_method(*self.http_method_names)

    @overload
    def _check_http_method(self) -> NoReturn: ...
    @overload
    def _check_http_method(self, *allowed_methods: str) -> None: ...
    @final
    def _check_http_method(self, *allowed_methods: str) -> None:
        '''检查请求类型，准备和处理函数应做好相应的检查'''
        if self.request.method.lower() not in allowed_methods:
            response = self.http_method_not_allowed(self.request, *self.args, **self.kwargs)
            return self.response_created(response)

    def check_perm(self) -> None:
        '''
        检查用户是否登录及权限
        '''
        if self.login_required and not self.request.user.is_authenticated:
            return self.response_created(self.redirect_to_login(self.request))
        for perm in self.perms_required:
            if not self.request.user.has_perm(perm):
                return self.permission_denied()

    @final
    def redirect_to_login(self, request: HttpRequest,
                          login_url: str | None = None) -> HttpResponseRedirect:
        '''
        重定向用户至登录页，登录后跳转回当前页面

        :param request: 正在处理的请求
        :type request: HttpRequest
        :param login_url: 登录页，可包含GET参数，默认使用Django设置, defaults to None
        :type login_url: str, optional
        :return: 页面重定向
        :rtype: HttpResponseRedirect
        '''
        # 相对路径，避免产生跨域问题
        path = request.get_full_path()
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(path, login_url, 'origin')

    def permission_denied(self, user_info: str | None = None) -> NoReturn:
        '''
        抛出用户提示，无权访问该页面，必须抛出异常

        :param user_info: 直接呈现给用户的附加信息, defaults to None
        :type user_info: str | None, optional
        '''
        user_message = f'无权访问该页面'
        if user_info is not None:
            user_message += f'：{user_info}'
        return self.response_created(self.http_forbidden(user_message))

    def http_forbidden(self, user_message: str = '') -> HttpResponse:
        return HttpResponseForbidden(user_message)

    def get_method_name(self, request: HttpRequest) -> str:
        return request.method.lower()

    def dispatch_prepare(self, method: str) -> str:
        '''
        每个方法执行前的准备工作，返回重定向的方法名
        
        被信任的方法，返回的函数名可以不在method_names中
        子类建议使用match语句
        不存在对应方法时，调用`default_prepare`
        '''
        default_name = f'check_{method}'
        if not hasattr(self, default_name):
            return self.default_prepare(method, default_name)
        prepare_func: SecureView._PrepareFuncType = getattr(self, default_name)
        # prepare_func返回str，重设method
        method = prepare_func()
        return method

    def default_prepare(self, method: str, default_name: str | None = None) -> str:
        '''不存在准备方法时，提供默认准备函数，SecureView抛出异常'''
        if default_name is None:
            default_name = f'check_{method}'
        raise ImproperlyConfigured(
            f'SecureView requires an implementation of `{default_name}`'
        )

    def error_response(self, exception: Exception) -> HttpResponse:
        '''错误处理，子类可重写，不应产生异常'''
        # TODO: 错误处理和http_method_not_allowed不同
        from boot.config import DEBUG
        if DEBUG: raise
        return self._check_http_method()

    def redirect(self, to: str, *args, permanent=False, **kwargs):
        '''重定向，由于类的重定向对象无需提前确定，使用redirect动态加载即可'''
        from django.shortcuts import redirect
        return self.response_created(redirect(to, *args, permanent=permanent, **kwargs))


class SecureTemplateView(SecureView):
    """
    通用的模板视图类：在SecureView的基础上增加了模板渲染功能

    模板渲染：
    - template_name对应模板的文件名，继承类必须设置这个属性
    - get_context_data()用于获取模板所需的context
    - extra_context作为get_context_data()的补充，在处理请求的过程中可以随时向其中添加内容
    """
    template_name: str
    extra_context: dict[str, Any]
    response_class = TemplateResponse

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        super().setup(request, *args, **kwargs)
        self.extra_context = {}

    def permission_denied(self, user_info: str | None = None,
                          context: dict[str, Any] | None = None) -> NoReturn:
        user_message = f'当前用户无权访问该页面'
        if user_info is not None:
            user_message += f'：{user_info}'
        if context is not None:
            self.extra_context.update(context)
        return self.response_created(self.wrong(user_message))

    def get_template_names(self):
        if getattr(self, 'template_name', None) is None:
            raise ImproperlyConfigured(
                "SecureTemplateView requires either a definition of "
                "'template_name' or an implementation of 'get_template_names()'"
            )
        return [self.template_name]

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        if self.extra_context is not None:
            kwargs.update(self.extra_context)
        return kwargs

    def render(self, **kwargs):
        response = self.response_class(
            request=self.request,
            template=self.get_template_names(),
            context=self.get_context_data(**kwargs),
        )
        return self.response_created(response)

    def wrong(self, message: str):
        wrong(message, self.extra_context)
        return self.render()

    def error_response(self, exception: Exception) -> HttpResponse:
        from utils.log import _format_request, get_logger
        _message = _format_request(self.request)
        get_logger('err').exception(_message)
        return super().error_response(exception)


class SecureJsonView(SecureView):
    response_class = JsonResponse

    def get_default_data(self) -> dict[str, Any]:
        # TODO: 默认的返回数据
        raise NotImplementedError

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        # TODO: 重写dispatch是不推荐的，super().dispatch之后的部分不捕获异常
        response = super().dispatch(request, *args, **kwargs)
        if isinstance(response, HttpResponseRedirect):
            return response
        if isinstance(response, dict):
            return self.response_class(data=response)
        if response is None:
            return self.response_class(data=self.get_default_data())
        else:
            raise TypeError

    def error_response(self, exception: Exception) -> HttpResponse:
        from utils.log import _format_request, get_logger
        _message = _format_request(self.request)
        get_logger('err').exception(_message)
        return super().error_response(exception)
