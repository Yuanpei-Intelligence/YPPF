from typing import Any

from app.log import except_captured

from django.views.generic import TemplateView
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.contrib.auth.decorators import login_required


class ArgMixin:
    """
    子类需要重写arg_check函数
    """
    args = {}  # get method args

    def is_arg_valid(self,
                     request: HttpRequest) -> 'HttpResponseRedirect | None':
        self.args = request.GET.dict()


class FormMixin:
    form_data = {}  # post method data

    def is_form_valid(self,
                      request: HttpRequest) -> 'HttpResponseRedirect | None':
        self.form_data = request.POST.dict()


class SecureView(TemplateView, ArgMixin, FormMixin):
    login_required = True
    redirect_field_name = "origin"
    source = ""

    def dispatch(self, request: HttpRequest, *args: Any,
                 **kwargs: Any) -> HttpResponse:
        def real_dispatch(request: HttpRequest, args, kwargs):
            # 检查get方法的参数
            response = self.is_arg_valid(request)
            if response is not None:
                return response
            if request.method == 'GET':
                return super(SecureView, self).dispatch(request, args, kwargs)

            # 检查post方法的参数
            response = self.is_form_valid(request)
            if response is not None:
                return response

            return super(SecureView, self).dispatch(request, args, kwargs)

        wrapped_dispatch = except_captured(source=self.source,
                                           record_user=True)(real_dispatch)
        if self.login_required:
            wrapped_dispatch = login_required(wrapped_dispatch,
                                              self.redirect_field_name)

        return wrapped_dispatch(request, args, kwargs)
