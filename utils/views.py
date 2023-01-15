from typing import Dict, List, Any

from django.views.generic import View
from django.http import HttpRequest, HttpResponseRedirect
from django.core.exceptions import ImproperlyConfigured
from django.template.response import TemplateResponse

from .log import err_capture

class SecureView(View):
    """
    通用的视图类

    主要功能：权限检查、方法分发、参数检查、模板渲染
    
    权限检查：
    - 可以根据需要重载check_perm()

    方法分发 + 参数检查：
    - 可以重载get_method_name()来实现request到method的映射
    - method_names列表存放所有可用的方法，默认有get、post两种方法
    - method_names里面的每个方法，都需要实现方法的同名函数method_name()，和参数检查函数check_method_name()

    模板渲染：
    - template_name对应模板的文件名，继承类必须设置这个属性
    - get_context_data()用于获取模板所需的context
    - extra_context作为get_context_data()的补充，可以按需向其中添加内容
    - render()进行模板渲染
    """

    login_required = True
    redirect_field_name = "index/"

    args : Dict[str, Any] | None = None  # GET方法的参数
    form_data : Dict[str, Any] | None = None  # 表单数据

    method_names : List[str] = ['get', 'post']

    template_name = None
    extra_context : Dict[str, Any] | None = None
    response_class = TemplateResponse

    def check_perm(self,
                   request: HttpRequest) -> 'HttpResponseRedirect | None':
        """
        检查用户权限
        """
        if self.login_required and not request.user.is_authenticated:
            return HttpResponseRedirect(self.redirect_field_name)

    def get_method_name(self,
                        request: HttpRequest) -> 'HttpResponseRedirect | str':
        return request.method.lower()

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
        response = self.check_perm(request)
        if response is not None:
            return response

        method_name = self.get_method_name(request)
        self.get_args(request)
        if method_name == 'post':
            self.get_form_data(request)

        if method_name in self.method_names:
            handler = getattr(self, method_name, self.http_method_not_allowed)
        else:
            handler = self.http_method_not_allowed
        if handler is self.http_method_not_allowed:
            return handler(request, *args, **kwargs)

        checker = getattr(self, 'check_' + method_name, self.undefined_checker)
        response = checker(request, method_name=method_name)
        if response is not None:
            return response

        return handler(request, *args, **kwargs)

    def get_template_names(self):
        if self.template_name is None:
            raise ImproperlyConfigured(
                "SecureView requires either a definition of "
                "'template_name' or an implementation of 'get_template_names()'"
            )
        else:
            return [self.template_name]

    def get_args(self, request: HttpRequest) -> None:
        self.args = request.GET.dict()

    def get_form_data(self, request: HttpRequest) -> None:
        self.form_data = request.POST.dict()

    def undefined_checker(self, **kwargs):
        raise ImproperlyConfigured(
            f"SecureView requires an implementation of '{kwargs['method_name']}_check()'"
        )
