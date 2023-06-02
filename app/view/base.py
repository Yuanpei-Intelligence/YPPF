from utils.http.dependency import UserRequest
from django.core.exceptions import ImproperlyConfigured

from utils.views import SecureView, SecureTemplateView, SecureJsonView
from app.log import ProfileLogger
from app.utils import get_sidebar_and_navbar


__all__ = ['ProfileView', 'ProfileTemplateView', 'ProfileJsonView']


class ProfileView(SecureView):
    request: UserRequest
    PrepareType = SecureView.NoReturnPrepareType | None

    check_access: bool = True
    need_prepare: bool = True
    logger_name: str

    def _check_access(self, redirect_url='/logout/') -> None:
        if not self.request.user.is_valid():
            return self.response_created(self.redirect(redirect_url))

    def _check_new_user(self, init_password: bool = True) -> None:
        if not self.request.user.is_newuser:
            return
        if self.request.session.get('confirmed') != 'yes':
            return self.response_created(self.redirect('/agreement/'))
        if init_password:
            return self.response_created(self.redirect('/modpw/'))

    def check_perm(self) -> None:
        # TODO: 统一本函数和工具函数check_user_access
        super().check_perm()
        if self.check_access:
            self._check_access()
            self._check_new_user()

    def dispatch_prepare(self, method: str):
        return self.default_prepare(method, return_needed=False,
                                    prepare_needed=self.need_prepare)

    def get_logger(self):
        return ProfileLogger.getLogger(self.logger_name)


class ProfileTemplateView(ProfileView, SecureTemplateView):
    logger_name: str = 'ProfileError'
    page_name: str

    def render(self, **kwargs):
        if not hasattr(self, 'page_name'):
            raise ImproperlyConfigured('page_name is not defined!')
        self.extra_context['bar_display'] = get_sidebar_and_navbar(
            self.request.user, self.page_name)
        return super().render(**kwargs)


class ProfileJsonView(ProfileView, SecureJsonView):
    logger_name: str = 'ProfileAPIerror'

    def json_response(self, extra_data = None, **kwargs):
        ProfileLogger.getLogger('recording').info('json_response')
        return super().json_response(extra_data, **kwargs)
