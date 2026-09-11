"""Shared website-code primitives; persisted salts and throttle scopes stay stable."""
import secrets
from datetime import datetime, timedelta
from typing import Literal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.crypto import salted_hmac

from generic.models import User
from app.config import CONFIG
from app.log import logger
from app.models import LoginChallenge, PasswordResetChallenge, PasswordResetThrottle
from utils.http.dependency import HttpRequest


CODE_SECONDS = CONFIG.password_reset_token_seconds
CODE_ATTEMPTS = CONFIG.password_reset_token_attempts
RATE_WINDOW = timedelta(
    seconds=CONFIG.password_reset_window_seconds)
RATE_LOCK = timedelta(
    seconds=CONFIG.password_reset_lock_seconds)
RETENTION = timedelta(
    seconds=CONFIG.password_reset_retention_seconds)
REQUEST_LIMITS = {
    PasswordResetThrottle.Scope.REQUEST_ACCOUNT:
        CONFIG.password_reset_request_limits['account'],
    PasswordResetThrottle.Scope.REQUEST_DEVICE:
        CONFIG.password_reset_request_limits['device'],
    PasswordResetThrottle.Scope.REQUEST_IP:
        CONFIG.password_reset_request_limits['ip'],
}
VERIFY_LIMITS = {
    PasswordResetThrottle.Scope.VERIFY_ACCOUNT:
        CONFIG.password_reset_verify_limits['account'],
    PasswordResetThrottle.Scope.VERIFY_DEVICE:
        CONFIG.password_reset_verify_limits['device'],
    PasswordResetThrottle.Scope.VERIFY_IP:
        CONFIG.password_reset_verify_limits['ip'],
}


Purpose = Literal['login', 'password_reset']
_CODE_SALTS = {
    'login': 'app.website-login.code-v1',
    'password_reset': 'app.password-reset.code-v2',
}
_PASSWORD_SALTS = {
    'login': 'app.website-login.password-state',
    'password_reset': 'app.password-reset.password-state',
}


class _RateLimited(Exception):
    pass


def digest(value: str, *, salt: str) -> str:
    return salted_hmac(salt, value).hexdigest()


def _canonical_username(username: str) -> str:
    normalized = User.normalize_username(username.strip())
    return (
        User.objects.filter(username__iexact=normalized)
        .values_list('username', flat=True)
        .first()
        or normalized
    )


def _client_ip(request: HttpRequest) -> str:
    """Use the direct peer address unless trusted proxies are configured."""
    return request.META.get('REMOTE_ADDR') or 'unknown'


def _device_identifier(request: HttpRequest) -> str:
    csrf_cookie = (
        request.META.get('CSRF_COOKIE')
        or request.COOKIES.get(settings.CSRF_COOKIE_NAME)
    )
    if csrf_cookie:
        return f'csrf:{csrf_cookie}'
    session_key = request.session.session_key
    if session_key is not None:
        return f'session:{session_key}'
    return f'ip:{_client_ip(request)}'


def request_context(request: HttpRequest, username: str) -> tuple[str, str, str]:
    return (
        _canonical_username(username),
        _client_ip(request),
        _device_identifier(request),
    )


def _locked_throttle(scope: PasswordResetThrottle.Scope, identifier: str,
                     now: datetime) -> PasswordResetThrottle:
    """Caller must be in an atomic block and acquire scopes in sorted order."""
    row, _ = PasswordResetThrottle.objects.select_for_update().get_or_create(
        scope=scope,
        identifier_digest=digest(identifier, salt=f'app.password-reset.throttle.{scope}'),
        defaults={'window_started_at': now},
    )
    return row


def consume_limits(
    identifiers: dict[PasswordResetThrottle.Scope, str],
    limits: dict[PasswordResetThrottle.Scope, int],
    now: datetime,
) -> bool:
    """Consume shared request/verification budgets, rolling back partial updates."""
    rows: list[tuple[PasswordResetThrottle, int]] = []
    try:
        with transaction.atomic():
            for scope in sorted(identifiers, key=str):
                row = _locked_throttle(scope, identifiers[scope], now)
                if (row.locked_until is not None
                        and now < row.locked_until):
                    raise _RateLimited
                if now >= row.window_started_at + RATE_WINDOW:
                    row.window_started_at = now
                    row.attempts = 0
                    row.locked_until = None
                rows.append((row, limits[scope]))

            for row, limit in rows:
                row.attempts += 1
                if row.attempts >= limit:
                    row.locked_until = now + RATE_LOCK
                row.save(update_fields=[
                    'window_started_at',
                    'attempts',
                    'locked_until',
                ])
    except _RateLimited:
        return False
    return True


def lock_limits(
    identifiers: dict[PasswordResetThrottle.Scope, str],
    now: datetime,
) -> None:
    with transaction.atomic():
        for scope in sorted(identifiers, key=str):
            row = _locked_throttle(scope, identifiers[scope], now)
            row.locked_until = now + RATE_LOCK
            row.save(update_fields=['locked_until'])


def verification_identifiers(
    username: str,
    ip_address: str,
    device_identifier: str,
) -> dict[PasswordResetThrottle.Scope, str]:
    return {
        PasswordResetThrottle.Scope.VERIFY_ACCOUNT: username,
        PasswordResetThrottle.Scope.VERIFY_DEVICE: device_identifier,
        PasswordResetThrottle.Scope.VERIFY_IP: ip_address,
    }


def check_request_rate(
    request: HttpRequest,
    username: str,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now()
    username, ip_address, device_identifier = request_context(
        request, username)
    return consume_limits(
        {
            PasswordResetThrottle.Scope.REQUEST_ACCOUNT: username,
            PasswordResetThrottle.Scope.REQUEST_DEVICE: device_identifier,
            PasswordResetThrottle.Scope.REQUEST_IP: ip_address,
        },
        REQUEST_LIMITS,
        now,
    )


def cleanup_code_state(
    *,
    now: datetime | None = None,
) -> None:
    """Delete credentials beyond retention and old throttle rows with no active lock."""
    now = now or datetime.now()
    cutoff = now - RETENTION
    with transaction.atomic():
        PasswordResetChallenge.objects.filter(
            expires_at__lt=cutoff).delete()
        LoginChallenge.objects.filter(expires_at__lt=cutoff).delete()
        PasswordResetThrottle.objects.filter(
            Q(locked_until__isnull=True) | Q(locked_until__lte=now),
            window_started_at__lt=cutoff,
        ).delete()


def code_digest(user_id: int, code: str, purpose: Purpose) -> str:
    return digest(f'{user_id}:{code}', salt=_CODE_SALTS[purpose])


def password_digest(password: str, purpose: Purpose) -> str:
    return digest(password, salt=_PASSWORD_SALTS[purpose])


def generate_code(user_id: int, purpose: Purpose) -> tuple[str, str]:
    """Choose a code absent from both retained histories; caller must lock the user."""
    for _ in range(10):
        code = f'{secrets.randbelow(1_000_000):06d}'
        login_digest = code_digest(user_id, code, 'login')
        reset_digest = code_digest(user_id, code, 'password_reset')
        if (not LoginChallenge.objects.filter(token_digest=login_digest).exists()
                and not PasswordResetChallenge.objects.filter(token_digest=reset_digest).exists()):
            return code, code_digest(user_id, code, purpose)
    logger.error('Verification code generation exhausted retries')
    raise RuntimeError('Verification code generation failed')


def is_valid_code_format(code: str) -> bool:
    return isinstance(code, str) and len(code) == 6 and code.isascii() and code.isdecimal()


def record_code_failure(challenge: LoginChallenge | PasswordResetChallenge, now: datetime) -> bool:
    """Record a failed attempt on a locked row; return whether it was invalidated."""
    if challenge.consumed_at is not None or challenge.invalidated_at is not None:
        return False
    challenge.failed_attempts += 1
    invalidated = challenge.failed_attempts >= CODE_ATTEMPTS
    if invalidated:
        challenge.invalidated_at = now
    challenge.save(update_fields=['failed_attempts', 'invalidated_at'])
    return invalidated
