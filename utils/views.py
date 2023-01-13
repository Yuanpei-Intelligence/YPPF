from typing import Any

from app.log import except_captured

from django.views import View
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.contrib.auth.decorators import login_required


class ParamCheckViewMixin:
    """
    子类需要重写param_check函数
    """
    params = {}  # get/post中需要用的参数放到这里

    def param_check(
            self, request: HttpRequest
    ) -> 'HttpResponse | HttpResponseRedirect | None':
        self.params = request.GET.dict()


class SecureView(View, ParamCheckViewMixin):
    login_required = True
    redirect_field_name = "origin"
    source = ""

    def dispatch(self, request: HttpRequest, *args: Any,
                 **kwargs: Any) -> HttpResponse:
        # param_check + dispatch
        def real_dispatch(request, args, kwargs):
            response = self.param_check(request)
            if response is not None:
                return response
            return super(SecureView, self).dispatch(request, args, kwargs)

        wrapped_dispatch = except_captured(source=self.source,
                                           record_user=True)(real_dispatch)
        if self.login_required:
            wrapped_dispatch = login_required(wrapped_dispatch,
                                              self.redirect_field_name)

        return wrapped_dispatch(request, args, kwargs)
