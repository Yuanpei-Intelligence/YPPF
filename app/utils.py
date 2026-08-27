import string
import random
import urllib.parse
import uuid
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from typing import cast, overload, Literal

import xlwt
import imghdr
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.db.models import Q
from django.shortcuts import redirect
from django.utils.crypto import constant_time_compare, salted_hmac
from utils.http.dependency import HttpResponse, HttpRequest, UserRequest

from utils.http.utils import get_ip
from app.utils_dependency import *
from app.log import logger
from app.models import (
    User,
    NaturalPerson,
    Organization,
    Position,
    Notification,
    Help,
    Participation,
    ModifyRecord,
    PasswordResetChallenge,
    PasswordResetThrottle,
)


PASSWORD_RESET_PURPOSE = 'password-reset'
PASSWORD_RESET_SIGNING_SALT = 'app.password-reset.token'
PASSWORD_RESET_TOKEN_SECONDS = CONFIG.password_reset_token_seconds
PASSWORD_RESET_TOKEN_ATTEMPTS = CONFIG.password_reset_token_attempts
PASSWORD_RESET_WINDOW = timedelta(
    seconds=CONFIG.password_reset_window_seconds)
PASSWORD_RESET_LOCK = timedelta(
    seconds=CONFIG.password_reset_lock_seconds)
PASSWORD_RESET_RETENTION = timedelta(
    seconds=CONFIG.password_reset_retention_seconds)
PASSWORD_RESET_REQUEST_LIMITS = {
    PasswordResetThrottle.Scope.REQUEST_ACCOUNT:
        CONFIG.password_reset_request_limits['account'],
    PasswordResetThrottle.Scope.REQUEST_DEVICE:
        CONFIG.password_reset_request_limits['device'],
    PasswordResetThrottle.Scope.REQUEST_IP:
        CONFIG.password_reset_request_limits['ip'],
}
PASSWORD_RESET_VERIFY_LIMITS = {
    PasswordResetThrottle.Scope.VERIFY_ACCOUNT:
        CONFIG.password_reset_verify_limits['account'],
    PasswordResetThrottle.Scope.VERIFY_DEVICE:
        CONFIG.password_reset_verify_limits['device'],
    PasswordResetThrottle.Scope.VERIFY_IP:
        CONFIG.password_reset_verify_limits['ip'],
}


class _PasswordResetRateLimited(Exception):
    pass


def _password_reset_digest(value: str, *, salt: str) -> str:
    return salted_hmac(salt, value).hexdigest()


def _canonical_password_reset_username(username: str) -> str:
    normalized = User.normalize_username(username.strip())
    return (
        User.objects.filter(username__iexact=normalized)
        .values_list('username', flat=True)
        .first()
        or normalized
    )


def _password_reset_client_ip(request: HttpRequest) -> str:
    """Use the direct peer address unless trusted proxies are configured."""
    return request.META.get('REMOTE_ADDR') or 'unknown'


def _password_reset_device_identifier(request: HttpRequest) -> str:
    csrf_cookie = (
        request.META.get('CSRF_COOKIE')
        or request.COOKIES.get(settings.CSRF_COOKIE_NAME)
    )
    if csrf_cookie:
        return f'csrf:{csrf_cookie}'
    session_key = request.session.session_key
    if session_key is not None:
        return f'session:{session_key}'
    return f'ip:{_password_reset_client_ip(request)}'


def _password_reset_context(request: HttpRequest, username: str):
    return (
        _canonical_password_reset_username(username),
        _password_reset_client_ip(request),
        _password_reset_device_identifier(request),
    )


def _consume_password_reset_limits(
    identifiers: dict[PasswordResetThrottle.Scope, str],
    limits: dict[PasswordResetThrottle.Scope, int],
    now: datetime,
) -> bool:
    rows: list[tuple[PasswordResetThrottle, int]] = []
    try:
        with transaction.atomic():
            for scope in sorted(identifiers, key=str):
                identifier_digest = _password_reset_digest(
                    identifiers[scope],
                    salt=f'app.password-reset.throttle.{scope}',
                )
                row, _ = (
                    PasswordResetThrottle.objects.select_for_update()
                    .get_or_create(
                        scope=scope,
                        identifier_digest=identifier_digest,
                        defaults={'window_started_at': now},
                    )
                )
                if (row.locked_until is not None
                        and now < row.locked_until):
                    raise _PasswordResetRateLimited
                if now >= row.window_started_at + PASSWORD_RESET_WINDOW:
                    row.window_started_at = now
                    row.attempts = 0
                    row.locked_until = None
                rows.append((row, limits[scope]))

            for row, limit in rows:
                row.attempts += 1
                if row.attempts >= limit:
                    row.locked_until = now + PASSWORD_RESET_LOCK
                row.save(update_fields=[
                    'window_started_at',
                    'attempts',
                    'locked_until',
                ])
    except _PasswordResetRateLimited:
        return False
    return True


def cleanup_password_reset_state(
    *,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now()
    cutoff = now - PASSWORD_RESET_RETENTION
    with transaction.atomic():
        PasswordResetChallenge.objects.filter(
            expires_at__lt=cutoff).delete()
        PasswordResetThrottle.objects.filter(
            Q(locked_until__isnull=True) | Q(locked_until__lte=now),
            window_started_at__lt=cutoff,
        ).delete()


def _lock_password_reset_limits(
    identifiers: dict[PasswordResetThrottle.Scope, str],
    now: datetime,
) -> None:
    with transaction.atomic():
        for scope in sorted(identifiers, key=str):
            identifier_digest = _password_reset_digest(
                identifiers[scope],
                salt=f'app.password-reset.throttle.{scope}',
            )
            row, _ = (
                PasswordResetThrottle.objects.select_for_update()
                .get_or_create(
                    scope=scope,
                    identifier_digest=identifier_digest,
                    defaults={'window_started_at': now},
                )
            )
            row.locked_until = now + PASSWORD_RESET_LOCK
            row.save(update_fields=['locked_until'])


def _password_reset_verification_identifiers(
    username: str,
    ip_address: str,
    device_identifier: str,
) -> dict[PasswordResetThrottle.Scope, str]:
    return {
        PasswordResetThrottle.Scope.VERIFY_ACCOUNT: username,
        PasswordResetThrottle.Scope.VERIFY_DEVICE: device_identifier,
        PasswordResetThrottle.Scope.VERIFY_IP: ip_address,
    }


def check_password_reset_request_rate(
    request: HttpRequest,
    username: str,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now()
    username, ip_address, device_identifier = _password_reset_context(
        request, username)
    return _consume_password_reset_limits(
        {
            PasswordResetThrottle.Scope.REQUEST_ACCOUNT: username,
            PasswordResetThrottle.Scope.REQUEST_DEVICE: device_identifier,
            PasswordResetThrottle.Scope.REQUEST_IP: ip_address,
        },
        PASSWORD_RESET_REQUEST_LIMITS,
        now,
    )


def create_password_reset_token(
    request: HttpRequest,
    user: User,
    *,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now()
    _, ip_address, device_identifier = _password_reset_context(
        request, user.username)
    challenge_id = uuid.uuid4()
    signed_value = signing.dumps(
        {
            'challenge': str(challenge_id),
            'user': user.pk,
            'purpose': PASSWORD_RESET_PURPOSE,
        },
        salt=PASSWORD_RESET_SIGNING_SALT,
        compress=True,
    )
    token = f'{challenge_id}.{signed_value}'

    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        PasswordResetChallenge.objects.create(
            id=challenge_id,
            user=locked_user,
            token_digest=_password_reset_digest(
                token, salt='app.password-reset.token-digest'),
            password_digest=_password_reset_digest(
                locked_user.password,
                salt='app.password-reset.password-state',
            ),
            device_digest=_password_reset_digest(
                device_identifier, salt='app.password-reset.device'),
            ip_digest=_password_reset_digest(
                ip_address, salt='app.password-reset.ip'),
            created_at=now,
            expires_at=now + timedelta(seconds=PASSWORD_RESET_TOKEN_SECONDS),
        )
    return token


def _record_password_reset_failure(
    challenge: PasswordResetChallenge,
    now: datetime,
) -> bool:
    if challenge.consumed_at is not None or challenge.invalidated_at is not None:
        return False
    challenge.failed_attempts += 1
    update_fields = ['failed_attempts']
    invalidated = False
    if challenge.failed_attempts >= PASSWORD_RESET_TOKEN_ATTEMPTS:
        challenge.invalidated_at = now
        update_fields.append('invalidated_at')
        invalidated = True
    challenge.save(update_fields=update_fields)
    return invalidated


def reset_password_from_token(
    request: HttpRequest,
    username: str,
    token: str,
    new_password: str,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now()
    username, ip_address, device_identifier = _password_reset_context(
        request, username)
    identifiers = _password_reset_verification_identifiers(
        username, ip_address, device_identifier)
    if not _consume_password_reset_limits(
        identifiers, PASSWORD_RESET_VERIFY_LIMITS, now):
        return False
    with transaction.atomic():
        try:
            challenge_prefix, signed_value = token.split('.', 1)
            challenge_id = uuid.UUID(challenge_prefix)
        except (AttributeError, TypeError, ValueError):
            return False

        challenge_user = PasswordResetChallenge.objects.filter(
            pk=challenge_id).values('user_id').first()
        if challenge_user is None:
            return False
        user = User.objects.select_for_update().get(
            pk=challenge_user['user_id'])
        challenge = PasswordResetChallenge.objects.select_for_update().get(
            pk=challenge_id)
        challenge_identifiers = {
            **identifiers,
            PasswordResetThrottle.Scope.VERIFY_ACCOUNT: user.username,
        }
        try:
            payload = signing.loads(
                signed_value,
                salt=PASSWORD_RESET_SIGNING_SALT,
                max_age=PASSWORD_RESET_TOKEN_SECONDS,
            )
        except signing.BadSignature:
            if _record_password_reset_failure(challenge, now):
                _lock_password_reset_limits(challenge_identifiers, now)
            return False

        valid = (
            payload.get('purpose') == PASSWORD_RESET_PURPOSE
            and payload.get('challenge') == str(challenge.id)
            and payload.get('user') == user.pk
            and User.objects.filter(
                pk=user.pk, username__iexact=username).exists()
            and challenge.consumed_at is None
            and challenge.invalidated_at is None
            and now <= challenge.expires_at
            and constant_time_compare(
                challenge.token_digest,
                _password_reset_digest(
                    token, salt='app.password-reset.token-digest'),
            )
            and constant_time_compare(
                challenge.password_digest,
                _password_reset_digest(
                    user.password,
                    salt='app.password-reset.password-state',
                ),
            )
            and constant_time_compare(
                challenge.device_digest,
                _password_reset_digest(
                    device_identifier, salt='app.password-reset.device'),
            )
            and constant_time_compare(
                challenge.ip_digest,
                _password_reset_digest(
                    ip_address, salt='app.password-reset.ip'),
            )
        )
        if not valid:
            if _record_password_reset_failure(challenge, now):
                _lock_password_reset_limits(challenge_identifiers, now)
            return False

        validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=['password'])
        challenge.consumed_at = now
        challenge.save(update_fields=['consumed_at'])
        return True


def check_user_access(redirect_url="/logout/", is_modpw=False):
    """
    Decorator for views that checks that the user is valid, redirecting
    to specific url if necessary. Then it checks that the user is not
    first time login, redirecting to the modify password page otherwise.
    """

    def actual_decorator(view_function):
        @wraps(view_function)
        def _wrapped_view(request: UserRequest, *args, **kwargs):
            if not request.user.is_valid():
                return redirect(redirect_url)

            # 如果是首次登陆，会跳转到用户须知的页面
            if request.user.is_newuser:
                if request.session.get('confirmed') != 'yes':
                    return redirect("/agreement/")
                if not is_modpw:
                    return redirect('/modpw/')

            return view_function(request, *args, **kwargs)

        return _wrapped_view

    return actual_decorator


# TODO: Handle ip blocking
_block_ips = set()


def block_attack(view_function):
    @wraps(view_function)
    def _wrapped_view(request: HttpRequest, *args, **kwargs):
        ip = get_ip(request)
        if ip in _block_ips:
            return HttpResponse(status=403)
        return view_function(request, *args, **kwargs)
    return _wrapped_view


def record_attack(except_type=None, as_attack=False):
    '''临时用于拦截ip的装饰器，在用户验证层下、错误捕获层上，需要整理本函数至其他位置'''
    # TODO: 重构代码，调整本函数位置
    if except_type is None:
        except_type = ()

    def actual_decorator(view_function):
        @block_attack
        @wraps(view_function)
        def _wrapped_view(request: HttpRequest, *args, **kwargs):
            ip = get_ip(request)
            is_attack, err = False, None
            try:
                return view_function(request, *args, **kwargs)
            except except_type as e:
                is_attack, err = as_attack, e
            except Exception as e:
                is_attack, err = not as_attack, e
            finally:
                if err is not None:
                    if not is_attack:
                        raise err
                    _block_ips.add(ip)
                    return HttpResponse(status=403)
        return _wrapped_view
    return actual_decorator


@overload
def get_classified_user(
    user: User, user_type: Literal[User.Type.PERSON], *,
    update: bool = False, activate: bool = False
) -> NaturalPerson: ...


@overload
def get_classified_user(
    user: User, user_type: Literal[User.Type.ORG], *,
    update: bool = False, activate: bool = False
) -> Organization: ...


@overload
def get_classified_user(
    user: User, user_type: str | None = ..., *,
    update: bool = False, activate: bool = False
) -> ClassifiedUser: ...


def get_classified_user(user: User, user_type: str | User.Type | None = None, *,
                        update=False, activate=False) -> ClassifiedUser:
    '''获取基础用户对应的用户对象

    Args:
        user(User): 用户对象
        user_type(str, optional): 用来指定模型类型，非法值抛出`AssertionError`

    Keyword Args:
        update(bool, optional): 获取带锁的对象，需要在事务中调用
        activate(bool, optional): 只获取活跃的用户，由对应的模型管理器检查

    Returns:
        ClassifiedUser: 用户实例

    Raises:
        AssertionError: 非法的用户类型
        DoesNotExist: 用户不存在，当用户是合法用户且不筛选时，可假设不抛出此异常
    '''
    model = None
    if user_type is None:
        if user.is_person():
            model = NaturalPerson
        elif user.is_org():
            model = Organization
    elif user_type in User.Type.Persons():
        model = NaturalPerson
    elif user_type == UTYPE_ORG:
        model = Organization
    if model is None:
        raise AssertionError(f"非法的用户类型：“{user_type}”")
    return model.objects.get_by_user(user, update=update, activate=activate)


# 保持之前的函数名接口
get_person_or_org = get_classified_user


def get_user_ava(obj: ClassifiedUser):
    try:
        return obj.get_user_ava()
    except:
        # TODO: get_user_ava不是必要方法，添加新类型时，如果未实现请修改
        raise AssertionError('任何用户都应该有对应的头像！')


def get_user_wallpaper(person: ClassifiedUser):
    if person.get_user().is_person():
        return MEDIA_URL + (str(person.wallpaper) or "wallpaper/person_wall_default.jpg")
    else:
        return MEDIA_URL + (str(person.wallpaper) or "wallpaper/org_wall_default.jpg")


# 检验是否要展示如何分享信息的帮助，预期只在stuinfo, orginfo, viewActivity使用
def get_inform_share(me: ClassifiedUser, is_myself=True):
    alert_message = ""
    if is_myself and me.inform_share:
        alert_message = ("【关于分享】:如果你在使用手机浏览器，" +
                         "可以使用浏览器自带的分享来分享你的主页或者活动主页，" +
                         "或者可以选择将其在微信/朋友圈中打开并分享。")
        # me.inform_share = False
        # me.save()
        return True, alert_message
    return False, alert_message


def get_sidebar_and_navbar(user: User, navbar_name="", title_name=""):
    '''
    YWolfeee Aug 16
    修改left siderbar的逻辑，统一所有个人和所有小组的左边栏，不随界面而改变
    这个函数负责统一get sidebar和navbar的内容，解决了信箱条数显示的问题
    user对象是request.user对象直接转移
    内容存储在bar_display中
    Attention: 本函数请在render前的最后时刻调用

    added by syb, 8.23:
    在函数中添加了title_name和navbar_name参数，根据这两个参数添加帮助信息
    现在最推荐的调用方式是：在views的函数中，写
    bar_display = utils.get_sidebar_and_navbar(user, title_name, navbar_name)
    '''
    bar_display = {}
    _utype = ""
    if user.is_person():
        _utype = "Person"
    elif user.is_org():
        _utype = "Organization"
    else:
        # TODO: 支持未认证用户
        raise AssertionError(f"非法的用户类型：“{_utype}”")

    me = get_person_or_org(user)  # 获得对应的对象
    bar_display["user_type"] = _utype
    if user.is_staff:
        bar_display["is_staff"] = True
    bar_display["user_active"] = user.active

    # 接下来填补各种前端呈现信息

    # 头像
    bar_display["avatar_path"] = get_user_ava(me)

    # 信箱数量
    bar_display["mail_num"] = Notification.objects.filter(
        receiver=user, status=Notification.Status.UNDONE
    ).count()

    if user.is_person():
        me = cast(NaturalPerson, me)
        # 是人则加载选课权限和地下室权限
        bar_display["course_permission"] = me.has_permission('select_course')
        bar_display["has_basement_permission"] = me.has_permission('underground_appointment')
        bar_display.update(
            profile_name="个人主页",
            profile_url="/stuinfo/",
            name=me.get_display_name(),
            person_type=me.identity,
            is_auditor=me.is_teacher(),
        )
    elif user.is_org():
        me = cast(Organization, me)
        bar_display.update(
            profile_name="小组主页",
            profile_url="/orginfo/",
            is_course=me.otype.otype_name == CONFIG.course.type_name,
        )

    # 个人组织都可以预约
    # 页面标题默认与侧边栏相同
    bar_display.update(
        underground_url=get_underground_site_url(),
        navbar_name=navbar_name,
        title_name=title_name if title_name else navbar_name,
    )

    if navbar_name:
        help_key = navbar_name
        if help_key == "我的元气值":
            help_key += _utype.lower()
        help_info = Help.objects.filter(title=navbar_name).first()
        bar_display.update(
            help_message=CONFIG.help_message.get(help_key, ""),
            help_paragraphs=help_info.content if help_info is not None else "",
        )

    return bar_display


def site_match(site, url, path_check_level=0, scheme_check=False):
    '''检查是否是同一个域名，也可以检查路径是否相同
    - path_check_level: 0-2, 不检查/忽视末尾斜杠/完全相同
    - scheme_check: bool, 协议是否相同
    '''
    site = urllib.parse.urlparse(site)
    url = urllib.parse.urlparse(url)
    if site.netloc != url.netloc:
        return False
    if scheme_check and site.scheme != url.scheme:
        return False
    if path_check_level:
        spath, upath = site.path, url.path
        if path_check_level > 1:
            spath, upath = spath.rstrip('/'), upath.rstrip('/')
        if spath != upath:
            return False
    return True


def get_std_url(arg_url: str, site_url: str, path_dir=None, match_func=None):
    '''
    检查是否匹配，返回(is_match, standard_url)，匹配时规范化url，否则返回原url

    Args
    ----
    - arg_url: 需要判断的url或者None，后者返回(False, site_url)
    - site_url: 规范的网址，其scheme, netloc和path部分被用于参考
    - path_dir: 需要保持一致的路径部分，默认为空
    - match_func: 检查匹配的函数，默认为site_match(site_url, arg_url)
    '''
    if match_func is None:
        match_func = lambda x: site_match(site_url, x)

    if arg_url is None:
        return False, site_url

    if match_func(arg_url):
        site_parse = urllib.parse.urlparse(site_url)
        arg_parse = urllib.parse.urlparse(arg_url)

        def in_dir(path, path_dir):
            return path.startswith(path_dir) or path == path_dir.rstrip('/')

        std_path = arg_parse.path
        if path_dir:
            if (in_dir(site_parse.path, path_dir) and not in_dir(std_path, path_dir)):
                std_path = path_dir.rstrip('/') + std_path
            elif (not in_dir(site_parse.path, path_dir) and in_dir(std_path, path_dir)):
                std_path = std_path.split(path_dir.rstrip('/'), 1)[1]

        std_parse = [
            site_parse.scheme,
            site_parse.netloc,
            std_path,
            arg_parse.params,
            arg_parse.query,
            arg_parse.fragment,
        ]
        arg_url = urllib.parse.urlunparse(std_parse)
        return True, arg_url
    return False, arg_url


def get_underground_site_url():
    from django.urls import reverse
    return reverse('Appointment:root')


def get_std_underground_url(underground_url):
    '''检查是否是地下室网址，返回(is_underground, standard_url)
    - 如果是，规范化网址，否则返回原URL
    - 如果参数为None，返回URL为地下室网址'''
    # TODO: raise DeprecationWarning('不再兼容多网址')
    site_url = get_underground_site_url()
    return get_std_url(underground_url, site_url)
    if underground_url is None:
        underground_url = site_url
    if site_match(site_url, underground_url):
        underground_url = urllib.parse.urlunparse(
            urllib.parse.urlparse(site_url)[:2]
            + urllib.parse.urlparse(underground_url)[2:])
        return True, underground_url
    return False, underground_url


def get_url_params(request, html_display):
    raise NotImplementedError
    full_path = request.get_full_path()
    if "?" in full_path:
        params = full_path.split["?"][1]
        params = params.split["&"]
        for param in params:
            key, value = param.split["="][0], param.split["="][1]
            if key not in html_display.keys():  # 禁止覆盖
                html_display[key] = value


def if_image(image):
    '''判断是否为图片'''
    if image is None:
        return 0
    imgType_list = {"jpg", "bmp", "png", "jpeg", "rgb", "tif"}

    if imghdr.what(image) in imgType_list:
        return 2  # 为图片
    return 1  # 不是图片


def random_code_init(seed):
    '''用于新建小组时，根据种子生成6位伪随机密码（如果种子可知则密码可知）'''
    b = string.digits + string.ascii_letters  # 构建密码池
    random.seed(seed)
    password = ''.join(random.choices(b, k=6))
    return password


def check_account_setting(request: UserRequest):
    if request.user.is_person():
        html_display = dict()
        attr_dict = dict()

        html_display['warn_code'] = 0
        html_display['warn_message'] = ""

        attr_dict['nickname'] = request.POST["nickname"]
        attr_dict['biography'] = request.POST["aboutBio"]
        attr_dict['telephone'] = request.POST["tel"]
        attr_dict['email'] = request.POST["email"]
        attr_dict['stu_major'] = request.POST["major"]
        # attr_dict['stu_grade'] = request.POST['grade'] 用户无法填写
        # attr_dict['stu_class'] = request.POST['class'] 用户无法填写
        attr_dict['stu_dorm'] = request.POST['dorm']
        attr_dict['ava'] = request.FILES.get("avatar")
        attr_dict['gender'] = request.POST['gender']
        attr_dict['birthday'] = request.POST['birthday']
        attr_dict['accept_promote'] = request.POST['accept_promote']
        attr_dict['wechat_receive_level'] = request.POST['wechat_receive_level']
        attr_dict['wallpaper'] = request.FILES.get("wallpaper")

        show_dict = dict()

        show_dict['show_nickname'] = request.POST.get('show_nickname') == 'on'
        show_dict['show_gender'] = request.POST.get('show_gender') == 'on'
        show_dict['show_birthday'] = request.POST.get('show_birthday') == 'on'
        show_dict['show_tel'] = request.POST.get('show_tel') == 'on'
        show_dict['show_email'] = request.POST.get('show_email') == 'on'
        show_dict['show_major'] = request.POST.get('show_major') == 'on'
        show_dict['show_dorm'] = request.POST.get('show_dorm') == 'on'

        # 合法性检查
        """if len(attr_dict['nickname']) > 20:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的昵称过长，不能超过20个字符哦！" 
        """

        if len(attr_dict['biography']) > 1024:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的简介过长，不能超过1024个字符哦！"

        if len(attr_dict['stu_major']) > 25:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的专业过长，不能超过25个字符哦！"

        if len(attr_dict['stu_dorm']) > 6:
            html_display['warn_code'] = 1
            html_display['warn_message'] += "输入的宿舍过长，不能超过6个字符哦！"
    else:
        html_display = dict()
        attr_dict = dict()
        show_dict = dict()
        html_display['warn_code'] = 0
        html_display['warn_message'] = ""
        attr_dict['introduction'] = request.POST['introduction']
        attr_dict['tags_modify'] = request.POST['tags_modify']
    return attr_dict, show_dict, html_display

# 导出Excel文件


def export_activity(activity, inf_type):

    # 设置HTTPResponse的类型
    response = HttpResponse(content_type='application/vnd.ms-excel')
    if activity is None:
        return response
    response['Content-Disposition'] = f'attachment;filename={activity.title}.xls'
    participants: QuerySet[Participation] = SQ.sfilter(Participation.activity, activity)
    if inf_type == "sign":  # 签到信息
        participants = participants.filter(status=Participation.AttendStatus.ATTENDED)
    elif inf_type == "enroll":  # 报名信息
        participants = participants.exclude(status=Participation.AttendStatus.CANCELED)
    else:
        return response
        """导出excel表"""
    if len(participants) > 0:
        # 创建工作簿
        ws = xlwt.Workbook(encoding='utf-8')
        # 添加第一页数据表
        w = ws.add_sheet('sheet1')  # 新建sheet（sheet的名称为"sheet1"）
        # 写入表头
        w.write(0, 0, u'姓名')
        w.write(0, 1, u'学号')
        w.write(0, 2, u'年级/班级')
        if inf_type == "enroll":
            w.write(0, 3, u'报名状态')
            w.write(0, 4, u'注：报名状态为“已参与”时表示报名成功并成功签到，“未签到”表示报名成功但未签到，'
                          u'"已报名"表示报名成功，“活动申请失败”表示在抽签模式中落选，“申请中”则表示抽签尚未开始。')
        # 写入数据
        excel_row = 1
        for participant in participants:
            name = participant.person.name
            Sno = participant.person.person_id.username
            grade = str(participant.person.stu_grade) + '级' + \
                str(participant.person.stu_class) + '班'
            if inf_type == "enroll":
                status = participant.status
                w.write(excel_row, 3, status)
            # 写入每一行对应的数据
            w.write(excel_row, 0, name)
            w.write(excel_row, 1, Sno)
            w.write(excel_row, 2, grade)
            excel_row += 1
        # 写出到IO
        output = BytesIO()
        ws.save(output)
        # 重新定位到开始
        output.seek(0)
        response.write(output.getvalue())
    return response


# 导出小组成员信息Excel文件
def export_orgpos_info(org):
    # 设置HTTPResponse的类型
    response = HttpResponse(content_type='application/vnd.ms-excel')
    if org is None:
        return response
    response['Content-Disposition'] = f'attachment;filename=小组{org.oname}成员信息.xls'
    participants = Position.objects.activated().filter(
        org=org).filter(status=Position.Status.INSERVICE)
    """导出excel表"""
    if len(participants) > 0:
        # 创建工作簿
        ws = xlwt.Workbook(encoding='utf-8')
        # 添加第一页数据表
        w = ws.add_sheet('sheet1')  # 新建sheet（sheet的名称为"sheet1"）
        # 写入表头
        w.write(0, 0, u'姓名')
        w.write(0, 1, u'学号')
        w.write(0, 2, u'职位')
        # 写入数据
        excel_row = 1
        for participant in participants:
            name = participant.person.name
            Sno = participant.person.person_id.username
            pos = org.otype.get_name(participant.pos)
            # 写入每一行对应的数据
            w.write(excel_row, 0, name)
            w.write(excel_row, 1, Sno)
            w.write(excel_row, 2, pos)
            excel_row += 1
        # 写出到IO
        output = BytesIO()
        ws.save(output)
        # 重新定位到开始
        output.seek(0)
        response.write(output.getvalue())
    return response


def escape_for_templates(text: str):
    return text.strip().replace("\r", "").replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


def record_modification(user: User, info=""):
    try:
        obj = get_person_or_org(user)
        name = obj.get_display_name()
        firsttime = not user.modify_records.exists()
        ModifyRecord.objects.create(
            user=user, usertype=user.utype, name=name, info=info)
        return firsttime
    except:
        return None


def get_modify_rank(user: User):
    try:
        records = user.modify_records.all()
        if not records:
            return -1
        first = records.order_by('time')[0]
        rank = ModifyRecord.objects.filter(
            usertype=user.utype,
            time__lte=first.time,
        ).values('user').distinct().count()
        return rank
    except:
        return -1


def record_modify_with_session(request: UserRequest, info=""):
    try:
        recorded = record_modification(request.user, info)
        if recorded == True:
            rank = get_modify_rank(request.user)
            info_rank = CONFIG.max_inform_rank.get(request.user.utype, -1)
            if rank > -1 and rank <= info_rank:
                msg = (
                    f'您是第{rank}名修改账号信息的' +
                    ('个人' if request.user.is_person() else '小组') +
                    '用户！保留此截图可在游园会兑换奖励！'
                )
                request.session['alert_message'] = msg
    except:
        pass


def update_related_account_in_session(request, username, shift=False, oname=""):
    """
    外层保证 username 是一个自然人的 username 并且合法

    登录时 shift 为 false，切换时为 True，并设置request.user
    切换到某个组织时 oname 不为空，否则都是空
    """

    try:
        np = NaturalPerson.objects.activated().get(
            SQ.mq(NaturalPerson.person_id, username=username))
    except:
        return False
    orgs = list(Position.objects.activated().filter(
        is_admin=True, person=np).values_list("org__oname", flat=True))

    if oname:
        if oname not in orgs:
            return False
        orgs.remove(oname)
        user = Organization.objects.get(oname=oname).get_user()
    else:
        user = np.get_user()

    if shift:
        auth.logout(request)
        auth.login(request, user)

    request.session["Incharge"] = orgs
    request.session["NP"] = username

    return True


@logger.secure_func(raise_exc=True)
def user_login_org(request: UserRequest, org: Organization) -> MESSAGECONTEXT:
    '''
    令人疑惑的函数，需要整改
    尝试从用户登录到org指定的组织，如果不满足权限，则会返回wrong
    返回wrong或succeed，并更新request.user
    '''
    user = request.user
    try:
        assert user.is_person()
        me = NaturalPerson.objects.get_by_user(user, activate=True)
    except:
        return wrong("您没有权限访问该网址！请用对应小组账号登陆。")
    # 是小组一把手
    try:
        position = Position.objects.activated().filter(org=org, person=me)
        assert len(position) == 1
        position = position[0]
        assert position.is_admin
    except:
        return wrong("没有登录到该小组账户的权限!")
    # 到这里, 是本人小组并且有权限登录
    auth.logout(request)
    auth.login(request, org.get_user())  # 切换到小组账号
    update_related_account_in_session(request, user.username, oname=org.oname)
    return succeed("成功切换到小组账号处理该事务，建议事务处理完成后退出小组账号。")
