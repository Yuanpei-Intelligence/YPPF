from typing import Any, final, overload, TypedDict, NoReturn, Callable

from django.views.generic import View
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden, JsonResponse
from django.core.exceptions import ImproperlyConfigured
from django.template.response import TemplateResponse

from .http import HttpRequest
from .global_messages import wrong, MESSAGECONTEXT, MSG_FIELD, CODE_FIELD

try:
    # TODO: 获取类型提示，但Logger不是可靠工具包，部分依赖于设置
    from utils.log.logger import Logger
except:
    pass


__all__ = [
    'SecureView',
    'SecureJsonView',
    'SecureTemplateView',
]


class ResponseCreated(Exception):
    '''标识response已经被创建，不再需要继续处理'''
    def __init__(self, response: HttpResponse | None = None) -> None:
        self.response = response


_HandlerFuncType = Callable[[], HttpResponse]
_PrepareFuncType = Callable[[], _HandlerFuncType]


class SecureView(View):
    """
    通用的视图类基类

    主要功能：权限检查、方法分发、参数检查

    约定：
    - 以_开头的属性为私有属性，默认只对当前类有效，其它属性对子类有效
    - 以_开头的方法为类方法，子类可用，不建议覆盖

    权限检查：
    - 可以根据需要设置perms_required，访问者需要同时具有所有权限才能访问

    方法分发 + 参数检查：
    - 通过`get_method_name`获取`dispatch_prepare`参数名，被`method_names`检查
    - 通过`dispatch_prepare`执行该参数的准备过程，并获取处理函数
    - 准备函数和处理函数分别对应`class.PrepareType`类型和`class.HandlerType`类型
    - 调用处理函数处理最终请求，实现业务逻辑
    - 子类可以重载`_dispatch`以强化分发的功能，不建议重载`dispatch`
    """
    # 由View.setup自动设置，在子类修改以提供更多类型提示信息
    request: HttpRequest
    _ArgType = tuple
    args: _ArgType
    # 子类可用KWBaseType重写_KWType以提供更多类型提示信息
    # 写法：_KWType = SecureView.KWBaseType('_KWType', {参数名: 类型, ...})
    KWBaseType = TypedDict
    _KWType = KWBaseType('_KWType', {})
    kwargs: _KWType
    # 类的PrepareType和HandlerType定义准备函数和处理函数的类型与必要性
    # 子类可以重写PrepareType和HandlerType，但必须符合对应类型，其他名称无效
    PrepareType = _PrepareFuncType
    HandlerType = _HandlerFuncType
    # 子类可能允许准备函数不存在或不返回
    # 允许时应该声明PrepareType = SecureView.NoReturnPrepareType等
    NoReturnPrepareType = Callable[[], _HandlerFuncType | None]

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
            return self._check_http_methods()

        # Prepare and decide final handler
        handler = self.dispatch_prepare(method_name)

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
        self._check_http_methods(*self.http_method_names)

    @overload
    def _check_http_methods(self) -> NoReturn: ...
    @overload
    def _check_http_methods(self, *allowed_methods: str) -> None: ...
    @final
    def _check_http_methods(self, *allowed_methods: str) -> None:
        '''检查请求类型，准备和处理函数应做好相应的检查'''
        if self.request.method.lower() not in allowed_methods:
            response = self.http_method_not_allowed(self.request,
                                                    *self.args, **self.kwargs)
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

    def dispatch_prepare(self, method: str) -> _HandlerFuncType:
        '''
        每个方法执行前的准备工作，返回重定向的方法

        准备方法的约定以当前类PrepareType为准，PrepareType包含None的可只实现处理方法
        SecureView要求必须实现准备方法，子类如果准备方法命名错误未调用则无法提供错误信息
        子类建议使用match语句，不存在时可调用`default_prepare`
        '''
        return self.default_prepare(method, prepare_needed=True)

    @final
    def default_prepare(self, method: str, default_name: str | None = None, 
                        prepare_needed: bool = True,
                        return_needed: bool = True) -> _HandlerFuncType:
        '''
        默认准备函数，查找并调用特定方法的默认准备函数，不存在时尝试返回处理函数

        :param method: 处理函数名
        :type method: str
        :param default_name: 方法准备函数名，默认是prepare_{方法}, defaults to None
        :type default_name: str | None, optional
        :param prepare_needed: 是否必须执行准备函数, defaults to True
        :type prepare_needed: bool, optional
        :raises ImproperlyConfigured: 必须执行准备函数时，准备函数不存在
        :raises ImproperlyConfigured: 允许且准备函数不存在时，处理函数不存在
        :return: 处理函数
        :rtype: _HandlerFuncType
        '''
        if default_name is None:
            default_name = f'prepare_{method}'
        if getattr(self, default_name, None) is None:
            if prepare_needed:
                raise ImproperlyConfigured(
                    f'SecureView requires an implementation of `{default_name}`'
                )
        else:
            prepare_func: _PrepareFuncType = getattr(self, default_name)
            handler_func = prepare_func()
            if handler_func is not None:
                return handler_func
            if return_needed:
                raise ImproperlyConfigured(
                    f'`{default_name}` is required to return a function')
        if getattr(self, method, None) is not None:
            handler_func: _HandlerFuncType = getattr(self, method)
            return handler_func
        raise ImproperlyConfigured(
            f'SecureView requires an implementation of `{method}`')

    def get_logger(self) -> 'Logger | None':
        '''获取日志记录器'''
        return None

    def error_response(self, exception: Exception) -> HttpResponse:
        '''错误处理，异常栈可追溯，生产环境不应产生异常'''
        logger = self.get_logger()
        if logger is not None:
            logger.on_exception()
        return self.http_forbidden('出现错误，请联系管理员')

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

    def permission_denied(self, user_info: str | None = None) -> NoReturn:
        user_message = f'当前用户无权访问该页面'
        if user_info is not None:
            user_message += f'：{user_info}'
        return self.response_created(self.wrong(user_message))

    def get_template_names(self):
        if getattr(self, 'template_name', None) is None:
            raise ImproperlyConfigured(
                "SecureTemplateView requires either a definition of "
                "'template_name' or an implementation of 'get_template_names()'"
            )
        return [self.template_name]

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        return self.extra_context | kwargs

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

    def get_logger(self) -> 'Logger | None':
        from utils.log import get_logger
        return get_logger('error')


class SecureJsonView(SecureView):
    response_class: type[JsonResponse] = JsonResponse
    data: dict[str, Any]
    http_method_names = ['post']
    method_names = http_method_names

    ExtraDataType = dict[str, Any] | None

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        '''初始化请求参数和返回数据'''
        self.data = {}
        return super().setup(request, *args, **kwargs)

    def json_response(self, extra_data: ExtraDataType = None, **kwargs: Any) -> JsonResponse:
        data = self.data
        if extra_data is not None:
            data |= extra_data
        return self.response_class(data, **kwargs)

    def message_response(self, message: MESSAGECONTEXT):
        self.data[MSG_FIELD] = message[MSG_FIELD]
        self.data[CODE_FIELD] = message[CODE_FIELD]
        return self.json_response()

    def get_logger(self) -> 'Logger | None':
        from utils.log import get_logger
        return get_logger('APIerror')
