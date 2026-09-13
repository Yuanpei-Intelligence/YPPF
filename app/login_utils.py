"""Website code login. Account/IP/device budgets are shared with password reset."""
from datetime import datetime, timedelta

from django.db import transaction
from django.utils.crypto import constant_time_compare

from generic.models import User
from app.models import LoginChallenge, NaturalPerson
from app.auth_code_utils import (
    CODE_ATTEMPTS, CODE_SECONDS, VERIFY_LIMITS, check_request_rate, code_digest,
    consume_limits, generate_code, is_valid_code_format, password_digest,
    record_code_failure, request_context, verification_identifiers,
)
from utils.http.dependency import HttpRequest


def prepare_login_delivery(
    request: HttpRequest, username: str, *, now: datetime | None = None,
) -> tuple[int, str, str, str | None, str] | None:
    """Issue one login code and return its account and registered recipients."""
    # 1. 固定本次操作时间，先检查账号、设备和 IP 的共享发送限额。
    now = now or datetime.now()
    if not check_request_rate(request, username, now=now):
        return None

    # 2. 锁定账号后确认个人身份，串行处理同一账号的签发请求。
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username__iexact=username).first()
        if user is None or not user.is_person() or not user.is_valid():
            return None
        person = NaturalPerson.objects.filter(person_id=user).first()
        if person is None:
            return None

        # 3. 生成与两种用途历史记录都不冲突的码，原子替换旧登录凭证。
        code, token_digest = generate_code(user.pk, 'login')
        LoginChallenge.objects.filter(user=user, consumed_at__isnull=True,
                                      invalidated_at__isnull=True).update(invalidated_at=now)
        LoginChallenge.objects.create(
            user=user, token_digest=token_digest, password_digest=password_digest(user.password, 'login'),
            created_at=now, expires_at=now + timedelta(seconds=CODE_SECONDS))

        # 4. 返回收件信息和同一个码；退出事务后由投递层发送。
        return user.pk, user.username, person.name, person.email, code


def consume_login_code(
    request: HttpRequest, username: str, code: str, *, now: datetime | None = None,
) -> User | None:
    """Consume only LOGIN proof; never change passwords or set a reset bypass."""
    # 1. 扣除共享验证额度，再检查码格式，避免用无效输入绕过限流。
    now = now or datetime.now()
    username, ip, device = request_context(request, username)
    identifiers = verification_identifiers(username, ip, device)
    if not consume_limits(identifiers, VERIFY_LIMITS, now):
        return None
    if not is_valid_code_format(code):
        return None

    # 2. 按账号、凭证的顺序加锁，并重新确认个人账号资格。
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username__iexact=username).first()
        if user is None or not user.is_person() or not user.is_valid():
            return None
        if not NaturalPerson.objects.filter(person_id=user).exists():
            return None
        challenge = LoginChallenge.objects.select_for_update().filter(
            user=user, consumed_at__isnull=True, invalidated_at__isnull=True).order_by('-pk').first()
        if challenge is None:
            return None

        # 3. 校验有效期、尝试次数、登录码摘要及签发时的密码状态。
        valid = (now < challenge.expires_at
                 and challenge.failed_attempts < CODE_ATTEMPTS
                 and constant_time_compare(challenge.token_digest, code_digest(user.pk, code, 'login'))
                 and constant_time_compare(challenge.password_digest, password_digest(user.password, 'login')))
        if not valid:
            record_code_failure(challenge, now)
            return None

        # 4. 一次性消费凭证；仅返回账号，由视图建立登录会话。
        challenge.consumed_at = now
        challenge.save(update_fields=['consumed_at'])
        return user
