from typing import Dict, List, Any

from django.views.generic import View
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.core.exceptions import ImproperlyConfigured
from django.template.response import TemplateResponse

from .log import err_capture


class SecureView(View):
    """
    通用的视图类

    主要功能：权限检查、方法分发、参数检查

    权限检查：
    - 可以根据需要重载check_perm()

    方法分发 + 参数检查：
    - 可以重载get_method_name()来实现request到method的映射
    - method_names列表存放所有可用的方法，默认有get、post两种方法
    - method_names里面的每个方法，都需要实现方法的同名函数method_name()，和参数检查函数check_method_name()
    """

    login_required = True

    args: Dict[str, Any] | None = None  # GET方法的参数
    form_data: Dict[str, Any] | None = None  # 表单数据

    method_names: List[str] = ['get', 'post']
    response_class = None

    def check_perm(self,
                   request: HttpRequest) -> HttpResponse | None:
        """
        检查用户是否登录及权限
        """
        if self.login_required and not request.user.is_authenticated:
            return HttpResponseRedirect('/?origin=' + request.path)

    def permission_denied(self, context: Dict[str, Any]) -> HttpResponse:
        raise NotImplementedError

    def get_method_name(self, request: HttpRequest) -> HttpResponse | str:
        return request.method.lower()  # type: ignore

    @err_capture()
    def dispatch(self, request: HttpRequest, *args, **kwargs):
        # Check permission
        response = self.check_perm(request)
        if response is not None:
            return response

        # Decide handler
        method_name = self.get_method_name(request)
        if isinstance(method_name, HttpResponse):
            return method_name
        if method_name in self.method_names:
            handler = getattr(self, method_name, self.http_method_not_allowed)
        else:
            return self.http_method_not_allowed(request, *args, **kwargs)

        # Per method checker
        checker = getattr(self, 'check_' + method_name, None)
        if checker is None:
            raise ImproperlyConfigured(
                f'SecureView requires an implementation of "{method_name}_check"'
            )
        response = checker(request)
        if response is not None:
            return response

        # Handle
        response = handler(request, *args, **kwargs)
        if response is not None:
            return response

    def check_get(self, request: HttpRequest) -> HttpResponse | None:
        self.get_args(request)

    def check_post(self, request: HttpRequest) -> HttpResponse | None:
        self.get_args(request)
        self.get_form_data(request)

    def get_args(self, request: HttpRequest) -> None:
        self.args = request.GET.dict()

    def get_form_data(self, request: HttpRequest) -> None:
        self.form_data = request.POST.dict()


class SecureTemplateView(SecureView):
    """
    通用的模板视图类：在SecureView的基础上增加了模板渲染功能

    模板渲染：
    - template_name对应模板的文件名，继承类必须设置这个属性
    - get_context_data()用于获取模板所需的context
    - extra_context作为get_context_data()的补充，在处理请求的过程中可以随时向其中添加内容
    """
    template_name = None
    extra_context: Dict[str, Any] = dict()
    response_class = TemplateResponse

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse | None:
        pass

    def get_template_names(self):
        if self.template_name is None:
            raise ImproperlyConfigured(
                "SecureTemplateView requires either a definition of "
                "'template_name' or an implementation of 'get_template_names()'"
            )
        else:
            return [self.template_name]

    def get_context_data(self, **kwargs):
        if self.extra_context is not None:
            kwargs.update(self.extra_context)
        return kwargs

    def render(self, request: HttpRequest):
        return self.response_class(request=request,
                                   template=self.get_template_names(),
                                   context=self.get_context_data())

    @err_capture()
    def dispatch(self, request: HttpRequest, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if response is not None:
            return response

        return self.render(request)


class SecureJsonView(SecureView):
    response_class = JsonResponse

    def get_default_data() -> Dict[str, Any]:
        # TODO: 默认的返回数据
        pass

    @err_capture()
    def dispatch(self, request: HttpRequest, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if isinstance(response, HttpResponseRedirect):
            return response
        if isinstance(response, dict):
            return self.response_class(data=response)
        if response is None:
            return self.response_class(data=self.get_default_data)
        else:
            raise TypeError
