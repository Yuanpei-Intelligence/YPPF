"""
Domain operations of the 北大账号 binding (``timetable/README.md`` §3.3):
login through IAAA, the encrypted portal-session vault, consents, unbinding.

Every operation that touches both ``PkuAccount`` and ``PkuPortalSession``
runs inside ``transaction.atomic()``; network calls to IAAA / the portal
always happen *outside* of any transaction so no row lock is held while
waiting for pku.edu.cn.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.db import IntegrityError, transaction

from generic.models import User
from pku_account.config import CONFIG
from pku_account.crypto import InvalidToken, decrypt_json, encrypt_json
from pku_account.extern.iaaa import CaptchaRequired, IaaaError, OtpRequired
from pku_account.extern.portal import PortalClient
from pku_account.models import PkuAccount, PkuPortalSession

__all__ = [
    'BindingError',
    'PortalDisabled',
    'AccountLocked',
    'AlreadyBoundElsewhere',
    'NotBound',
    'SessionUnavailable',
    'login_and_bind',
    'get_binding',
    'get_client',
    'mark_session_ok',
    'invalidate_session',
    'update_consents',
    'unbind',
    'binding_payload',
]

logger = logging.getLogger(__name__)

# Length of ``PkuPortalSession.invalid_reason``.
_REASON_MAX_LENGTH = 64
_SESSION_EXPIRED_MESSAGE = '门户会话已失效，请重新登录'
_ALREADY_BOUND_MESSAGE = '该北大账号已绑定其他用户'


class BindingError(Exception):
    """Base class of the controlled failures raised by this module."""


class PortalDisabled(BindingError):
    """``pku_portal.enabled`` is false."""


class AccountLocked(BindingError):
    """Too many failed logins; ``locked_until`` says when to retry."""

    def __init__(self, locked_until: datetime):
        super().__init__('登录失败次数过多，请稍后再试')
        self.locked_until = locked_until


class AlreadyBoundElsewhere(BindingError):
    """The PKU account is already bound to a different YPPF user."""


class NotBound(BindingError):
    """The user has no PKU account binding."""


class SessionUnavailable(BindingError):
    """No binding, no stored session, or the session is marked invalid."""


# ---------------------------------------------------------------------------
# helpers


def _apply_consents(
    account: PkuAccount,
    now: datetime,
    *,
    timetable: bool | None,
    grades: bool | None,
) -> None:
    # ``None`` means "leave unchanged"; a timestamp is recorded whenever the
    # flag is explicitly set (granted or revoked) so audits see the decision.
    if timetable is not None:
        account.consent_timetable = bool(timetable)
        account.consent_timetable_at = now
    if grades is not None:
        account.consent_grades = bool(grades)
        account.consent_grades_at = now


def _record_login_failure(user: User, now: datetime) -> None:
    """Count a wrong-password login against an existing binding."""
    limit = max(1, CONFIG.max_login_failures)
    with transaction.atomic():
        account = (
            PkuAccount.objects.select_for_update().filter(user=user).first()
        )
        if account is None:
            return
        if account.locked_until is not None and account.locked_until <= now:
            # An expired lock starts a fresh counting window.
            account.login_failures = 0
            account.locked_until = None
        account.login_failures += 1
        if account.login_failures >= limit:
            account.locked_until = now + timedelta(seconds=CONFIG.lock_seconds)
        account.save(update_fields=['login_failures', 'locked_until'])
    if account.locked_until is not None:
        logger.info(
            'PKU binding of user #%s locked until %s after %s failures',
            user.pk, account.locked_until, account.login_failures,
        )


def _session_of(account: PkuAccount) -> PkuPortalSession | None:
    try:
        return account.portal_session
    except PkuPortalSession.DoesNotExist:
        return None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime('%Y-%m-%dT%H:%M:%S')


# ---------------------------------------------------------------------------
# public operations


def login_and_bind(
    user: User,
    username: str,
    password: str,
    *,
    consent_timetable: bool | None = None,
    consent_grades: bool | None = None,
) -> PkuAccount:
    """
    Log in through IAAA with the given credentials and (re)bind the result.

    On success the binding is created or updated, the fresh portal cookie
    jar replaces any stored session, the failure counter is reset and the
    consent flags are applied (``None`` leaves a flag unchanged). The
    password is used for this one IAAA request and never stored.

    Raises:
        PortalDisabled: the feature is switched off in ``config.json``.
        AccountLocked: the binding is locked because of earlier failures.
        AlreadyBoundElsewhere: ``username`` is bound to another user.
        IaaaError (incl. OtpRequired / CaptchaRequired): IAAA rejected the
            login; a plain wrong-password failure is counted against an
            existing binding and may lock it.
        PortalUnreachable: pku.edu.cn could not be reached.
    """
    if not CONFIG.enabled:
        raise PortalDisabled('北大门户登录功能未启用')
    username = username.strip()
    now = datetime.now()

    account = PkuAccount.objects.filter(user=user).first()
    if account is not None and account.is_locked(now):
        raise AccountLocked(account.locked_until)

    # Network I/O: deliberately outside of any transaction.
    try:
        client = PortalClient.login(username, password)
    except (CaptchaRequired, OtpRequired):
        # Not a wrong password: do not count it.
        raise
    except IaaaError:
        _record_login_failure(user, now)
        raise
    cookies = client.cookies()

    with transaction.atomic():
        # Serialize concurrent logins of the same user on their User row.
        User.objects.select_for_update().get(pk=user.pk)
        account = (
            PkuAccount.objects.select_for_update().filter(user=user).first()
        )
        if PkuAccount.objects.filter(pku_username=username).exclude(
            user=user
        ).exists():
            raise AlreadyBoundElsewhere(_ALREADY_BOUND_MESSAGE)
        if account is None:
            account = PkuAccount(user=user, verified_at=now)
        account.pku_username = username
        account.last_login_at = now
        account.login_failures = 0
        account.locked_until = None
        _apply_consents(
            account, now, timetable=consent_timetable, grades=consent_grades,
        )
        try:
            with transaction.atomic():
                account.save()
        except IntegrityError as exc:
            # Lost the race on the pku_username unique constraint.
            raise AlreadyBoundElsewhere(_ALREADY_BOUND_MESSAGE) from exc
        PkuPortalSession.objects.update_or_create(
            account=account,
            defaults={
                'cookies_encrypted': encrypt_json(cookies),
                'last_ok_at': now,
                'last_checked_at': now,
                'invalid': False,
                'invalid_reason': '',
            },
        )
    logger.info('PKU binding stored for user #%s', user.pk)
    return account


def get_binding(user: User) -> PkuAccount | None:
    """The user's binding, or ``None``."""
    return (
        PkuAccount.objects.select_related('portal_session')
        .filter(user=user)
        .first()
    )


def get_client(user: User) -> PortalClient:
    """
    Rebuild a :class:`PortalClient` from the stored session.

    Callers that then hit ``PortalSessionExpired`` must call
    :func:`invalidate_session` and ask the user to log in again.

    Raises:
        SessionUnavailable: no binding, no stored session, the session is
            marked invalid, or it cannot be decrypted any more (key rotated;
            the session is marked invalid in that case).
    """
    account = get_binding(user)
    if account is None:
        raise SessionUnavailable('尚未绑定北大账号')
    session = _session_of(account)
    if session is None:
        raise SessionUnavailable('没有可用的门户会话，请重新登录')
    if session.invalid:
        raise SessionUnavailable(_SESSION_EXPIRED_MESSAGE)
    try:
        cookies = decrypt_json(session.cookies_encrypted)
    except InvalidToken:
        logger.warning(
            'stored portal session of user #%s cannot be decrypted; '
            'marking it invalid', user.pk,
        )
        invalidate_session(account, 'key_changed')
        raise SessionUnavailable(_SESSION_EXPIRED_MESSAGE)
    if not isinstance(cookies, dict):
        invalidate_session(account, 'corrupted')
        raise SessionUnavailable(_SESSION_EXPIRED_MESSAGE)
    return PortalClient.from_cookies(cookies)


def mark_session_ok(account: PkuAccount, *, synced: bool = True) -> None:
    """
    Record that the stored session just worked. With ``synced`` (default)
    the binding's ``last_sync_at`` is updated as well, i.e. a consumer
    fetched data successfully; pass ``synced=False`` for a bare liveness
    probe.
    """
    now = datetime.now()
    with transaction.atomic():
        PkuPortalSession.objects.filter(account=account).update(
            last_ok_at=now, last_checked_at=now, invalid=False,
            invalid_reason='',
        )
        if synced:
            PkuAccount.objects.filter(pk=account.pk).update(last_sync_at=now)
            account.last_sync_at = now


def invalidate_session(account: PkuAccount, reason: str) -> None:
    """Mark the stored session unusable; ``reason`` is a short machine tag."""
    now = datetime.now()
    updated = PkuPortalSession.objects.filter(account=account).update(
        invalid=True, invalid_reason=reason[:_REASON_MAX_LENGTH],
        last_checked_at=now,
    )
    if updated:
        logger.info(
            'portal session of user #%s invalidated: %s',
            account.user_id, reason,
        )


def update_consents(
    user: User,
    *,
    timetable: bool | None = None,
    grades: bool | None = None,
) -> PkuAccount:
    """
    Set consent flags on the user's binding (``None`` = unchanged).

    Raises:
        NotBound: the user has no binding.
    """
    now = datetime.now()
    with transaction.atomic():
        account = (
            PkuAccount.objects.select_for_update().filter(user=user).first()
        )
        if account is None:
            raise NotBound('尚未绑定北大账号')
        _apply_consents(account, now, timetable=timetable, grades=grades)
        account.save(update_fields=[
            'consent_timetable', 'consent_timetable_at',
            'consent_grades', 'consent_grades_at',
        ])
    return account


def unbind(user: User) -> None:
    """Delete the binding and its stored session; a no-op when unbound."""
    with transaction.atomic():
        deleted, _ = PkuAccount.objects.filter(user=user).delete()
    if deleted:
        logger.info('PKU binding of user #%s removed', user.pk)


def binding_payload(account: PkuAccount | None) -> dict[str, Any]:
    """The ``Binding`` JSON shape of ``timetable/README.md`` §3.4."""
    if account is None:
        return {
            'bound': False,
            'pku_username': None,
            'verified_at': None,
            'last_login_at': None,
            'last_sync_at': None,
            'session': {
                'alive': None, 'last_ok_at': None, 'invalid_reason': '',
            },
            'consents': {'timetable': False, 'grades': False},
            'locked_until': None,
        }
    session = _session_of(account)
    if session is None:
        session_payload = {
            'alive': None, 'last_ok_at': None, 'invalid_reason': '',
        }
    else:
        session_payload = {
            'alive': not session.invalid,
            'last_ok_at': _iso(session.last_ok_at),
            'invalid_reason': session.invalid_reason,
        }
    now = datetime.now()
    return {
        'bound': True,
        'pku_username': account.pku_username,
        'verified_at': _iso(account.verified_at),
        'last_login_at': _iso(account.last_login_at),
        'last_sync_at': _iso(account.last_sync_at),
        'session': session_payload,
        'consents': {
            'timetable': account.consent_timetable,
            'grades': account.consent_grades,
        },
        'locked_until': (
            _iso(account.locked_until) if account.is_locked(now) else None
        ),
    }
