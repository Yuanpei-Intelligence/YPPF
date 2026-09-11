"""Issue password-reset credentials and consume them atomically with a password change."""
from datetime import datetime, timedelta

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils.crypto import constant_time_compare

from generic.models import User
from app.auth_code_utils import (
    CODE_ATTEMPTS, CODE_SECONDS, VERIFY_LIMITS, check_request_rate, code_digest,
    consume_limits, digest, generate_code, is_valid_code_format, lock_limits,
    password_digest, record_code_failure, request_context, verification_identifiers,
)
from app.models import NaturalPerson, PasswordResetChallenge
from utils.http.dependency import HttpRequest


__all__ = ['create_password_reset_token', 'prepare_password_reset_delivery', 'reset_password_from_token']


def _issue_code(user: User, ip: str, device: str, now: datetime) -> str:
    """Caller holds the account lock; generation and replacement share its transaction."""
    code, token_digest = generate_code(user.pk, 'password_reset')
    PasswordResetChallenge.objects.filter(
        user=user, consumed_at__isnull=True, invalidated_at__isnull=True,
    ).update(invalidated_at=now)
    PasswordResetChallenge.objects.create(
        user=user,
        token_digest=token_digest,
        password_digest=password_digest(user.password, 'password_reset'),
        device_digest=digest(device, salt='app.password-reset.device'),
        ip_digest=digest(ip, salt='app.password-reset.ip'),
        created_at=now,
        expires_at=now + timedelta(seconds=CODE_SECONDS),
    )
    return code


def create_password_reset_token(request: HttpRequest, user: User, *, now: datetime | None = None) -> str:
    """Issue a six-digit code, superseding old reset codes after locking the account.

    The existing Python name is retained; only code digests are stored. Arrange
    delivery after the transaction commits.
    """
    now = now or datetime.now()
    _, ip, device = request_context(request, user.username)
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        return _issue_code(locked_user, ip, device, now)


def prepare_password_reset_delivery(
    request: HttpRequest, username: str, *, now: datetime | None = None,
) -> tuple[int, str, str, str | None, str] | None:
    """Rate-limit and prepare one code for both channels after reserving queue capacity."""
    # 1. 固定操作时间，检查共享发送限额并提取请求标识。
    now = now or datetime.now()
    if not check_request_rate(request, username, now=now):
        return None
    username, ip, device = request_context(request, username)

    # 2. 锁定账号并确认个人资料，后续签发使用锁内读取的密码状态。
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username__iexact=username).first()
        if user is None or not user.is_person() or not user.is_valid():
            return None
        person = NaturalPerson.objects.filter(person_id=user).first()
        if person is None:
            return None

        # 3. 在当前事务中签发重置码并替换旧凭证，不重复获取账号锁。
        code = _issue_code(user, ip, device, now)

        # 4. 返回两个渠道共用的投递数据；真正发送发生在事务提交后。
        return user.pk, user.username, person.name, person.email, code


def reset_password_from_token(request: HttpRequest, username: str, token: str,
                              new_password: str, *, now: datetime | None = None) -> bool:
    """Consume a valid reset code only after password validation and successful change.

    Browser/IP values govern rate limits, not credential binding. Invalid codes
    return False; password validation errors leave the credential available.
    """
    # 1. 先扣除共享验证额度，再检查验证码格式。
    now = now or datetime.now()
    username, ip, device = request_context(request, username)
    identifiers = verification_identifiers(username, ip, device)
    if not consume_limits(identifiers, VERIFY_LIMITS, now):
        return False
    if not is_valid_code_format(token):
        return False

    # 2. 依次锁定账号和当前重置凭证，保证并发请求只能消费一次。
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username__iexact=username).first()
        if user is None:
            return False
        challenge = PasswordResetChallenge.objects.select_for_update().filter(
            user=user, consumed_at__isnull=True, invalidated_at__isnull=True,
        ).order_by('-created_at', '-pk').first()
        if challenge is None:
            return False

        # 3. 检查有效期、次数、重置码摘要和密码状态；失败达上限时锁定验证额度。
        valid = (
            now <= challenge.expires_at
            and challenge.failed_attempts < CODE_ATTEMPTS
            and constant_time_compare(challenge.token_digest, code_digest(user.pk, token, 'password_reset'))
            and constant_time_compare(challenge.password_digest, password_digest(user.password, 'password_reset'))
        )
        if not valid:
            if record_code_failure(challenge, now):
                lock_limits(identifiers, now)
            return False

        # 4. 先校验新密码，再将改密与凭证消费一起提交；校验失败仍可重试。
        validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=['password'])
        challenge.consumed_at = now
        challenge.save(update_fields=['consumed_at'])
        return True
