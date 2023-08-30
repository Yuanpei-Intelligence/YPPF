from typing import cast

from django.contrib import auth
from django.db import connection
from utils.http.dependency import HttpRequest, HttpResponse, UserRequest

from generic.models import User
from utils.global_messages import succeed
from utils.views import SecureTemplateView, SecureView
from app.models import Organization
from app.utils import update_related_account_in_session


class Index(SecureTemplateView):

    login_required = False
    template_name = 'index.html'

    def dispatch_prepare(self, method: str) -> SecureView.HandlerType:
        match method:
            case 'get':
                return (self.user_get
                        if self.request.user.is_authenticated else
                        self.visitor_get)
            case 'post':
                return self.prepare_login()
            case _:
                return self.default_prepare(method)

    def visitor_get(self) -> HttpResponse:
        # Modify password
        # Seems that after modification, log out by default?
        if self.request.GET.get('modinfo') is not None:
            succeed("修改密码成功!", self.extra_context)
        return self.render()

    def user_get(self) -> HttpResponse:
        self.request = cast(UserRequest, self.request)
        # Special user
        self.valid_user_check(self.request.user)

        # Logout
        if self.request.GET.get('is_logout') is not None:
            return self.redirect('logout')

        return self.redirect('welcome')

    def valid_user_check(self, user: User):
        # Special user
        if not user.is_valid():
            self.permission_denied(
                f'“{user.get_full_name()}”不存在成长档案，您可以登录其他账号'
            )

    def prepare_login(self) -> SecureView.HandlerType:
        assert 'username' in self.request.POST
        assert 'password' in self.request.POST
        _user = self.request.user
        assert not _user.is_authenticated or not cast(User, _user).is_valid()
        username = self.request.POST['username']
        # Check weather username exists
        if not User.objects.filter(username=username).exists():
            # Allow org to login with orgname
            org = Organization.objects.filter(oname=username).first()
            if org is None:
                return self.wrong('用户名不存在')
            username = org.get_user().username
        self.username = username
        self.password = self.request.POST['password']
        return self.login

    def login(self) -> HttpResponse:
        # Try login
        userinfo = auth.authenticate(username=self.username, password=self.password)
        if userinfo is None:
            return self.wrong('密码错误')

        # special user
        auth.login(self.request, userinfo)
        self.request = cast(UserRequest, self.request)
        self.valid_user_check(self.request.user)

        # first time login
        if self.request.user.is_newuser:
            return self.redirect('modpw')

        # Related account
        # When login as np, related org accout is also available
        update_related_account_in_session(self.request, self.username)

        # If origin is present and valid, redirect
        # Otherwise, redirect to welcome page
        origin = self.request.GET.get('origin')
        if origin and self._is_origin_safe(self.request, origin):
            return self.redirect(origin)
        else:
            return self.redirect('welcome')

    def _is_origin_safe(self, request: HttpRequest,
                        origin: str | None = None) -> bool:
        return origin is None or origin.startswith('/')


class Logout(SecureView):
    login_required = False

    def dispatch_prepare(self, method: str) -> SecureView.HandlerType:
        return self.get

    def get(self) -> HttpResponse:
        auth.logout(self.request)
        return self.redirect('index')


def healthcheck(request: HttpRequest) -> HttpResponse:
    """
    django健康状态检查
    尝试执行数据库操作，若成功返回200，不成功返回500
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            _ = cursor.fetchall()

        response = HttpResponse("healthy")
        response.status_code = 200
        return response
    except Exception:
        response = HttpResponse("unhealthy")
        response.status_code = 500
        return response
