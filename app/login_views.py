from functools import partial

from django import forms
from django.contrib import auth
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie

from app.login_utils import consume_login_code, prepare_login_delivery
from app.utils import update_related_account_in_session
from extern.code_delivery import queue_code_delivery
from utils.http.utils import safe_local_redirect_target
from utils.views import SecureTemplateView


class LoginCodeForm(forms.Form):
    username = forms.CharField(max_length=150)
    action = forms.ChoiceField(choices=[('send', 'send'), ('login', 'login')])
    code = forms.RegexField(r'^[0-9]{6}$', max_length=6, required=False)

    def clean(self):
        data = super().clean()
        if data.get('action') == 'login' and not data.get('code'):
            self.add_error('code', '请输入6位数字登录验证码')
        return data


@method_decorator(ensure_csrf_cookie, name='dispatch')
@method_decorator(csrf_protect, name='dispatch')
class CodeLogin(SecureTemplateView):
    """Public personal-account login; code proof never authorizes password reset.

    New users continue the existing agreement/initial-password onboarding.
    Existing users must still prove their old password at /modpw/.
    """
    login_required = False
    http_method_names = ['get', 'post']
    template_name = 'code_login.html'

    def dispatch_prepare(self, method):
        return self.handle

    def handle(self):
        request = self.request
        if request.user.is_authenticated:
            return redirect('welcome')
        if request.method == 'POST':
            form = LoginCodeForm(request.POST)
            self.extra_context['username'] = request.POST.get('username', '')
            if not form.is_valid():
                self.extra_context['error'] = '请填写账号和6位数字登录验证码'
            elif form.cleaned_data['action'] == 'send':
                queue_code_delivery('login', partial(
                    prepare_login_delivery, request, form.cleaned_data['username']))
                self.extra_context['message'] = '若账号及联系方式有效，登录验证码将发送至已绑定渠道'
            else:
                user = consume_login_code(request, form.cleaned_data['username'], form.cleaned_data['code'])
                if user is None:
                    self.extra_context['error'] = '登录验证码无效或已失效'
                else:
                    auth.login(request, user, backend='generic.backend.BlacklistBackend')
                    update_related_account_in_session(request, user.username)
                    if user.is_newuser:
                        return redirect('modpw')
                    return redirect(safe_local_redirect_target(request, request.GET.get('origin'), 'welcome'))
        return self.render()
