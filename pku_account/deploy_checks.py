"""
Deployment checks of the pku_account app, run by ``python manage.py deploy_check``.

Offline: the feature switch, the key that encrypts stored portal sessions and
the sync health of the last week — students who log in but never get a
successful import point at a portal-side change. On 2026-09-10 the portal
removed ``portal2017/bizcenter/course/getCourseInfo.do`` and
``portal2017/bizcenter/score/retrScores.do``; the client now reads
``publicQuery/ctrl/topic/myCourseTable/getCourseInfo.do`` and
``publicQuery/ctrl/topic/myScore/retrScores.do`` and reports a removed endpoint
as ``PortalEndpointMissing``, logging ``portal endpoint answered 404`` (the
elective fallback logs ``elective endpoint answered 404``). Online: IAAA
reachability.

There is deliberately no unauthenticated probe of the portal data endpoints:
without a session the old ``bizcenter`` paths answered 401 whether removed or
not, so such a probe cannot tell a live endpoint from a dead one.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator

import requests
from django.core.exceptions import ImproperlyConfigured

from pku_account.config import CONFIG
from pku_account.crypto import get_fernet
from pku_account.extern.iaaa import IAAA_OAUTH_URL
from pku_account.models import PkuAccount, PkuPortalSession

__all__ = ['checks', 'RECENT_DAYS']

RECENT_DAYS = 7


def checks(*, online: bool = False) -> Iterator[tuple[str, str, str]]:
    """Yield ``(level, name, detail)`` with level ``'OK'``, ``'WARN'`` or ``'FAIL'``."""
    if CONFIG.enabled:
        yield ('OK', 'pku_portal.enabled', 'portal login and server-side import on')
    else:
        yield ('WARN', 'pku_portal.enabled',
               'false: students can only paste their timetable or add entries by hand')

    try:
        get_fernet()
    except ImproperlyConfigured:
        yield ('FAIL', 'pku_portal.session_key',
               'not a valid Fernet key (generate one with Fernet.generate_key())')
    else:
        source = 'configured' if CONFIG.session_key else 'derived from SECRET_KEY'
        yield ('OK', 'pku_portal.session_key', source)

    yield _sync_health(datetime.now())

    if online:
        yield _iaaa_check()


def _sync_health(now: datetime) -> tuple[str, str, str]:
    since = now - timedelta(days=RECENT_DAYS)
    bound = PkuAccount.objects.count()
    logged_in = PkuAccount.objects.filter(last_login_at__gte=since).count()
    synced = PkuAccount.objects.filter(last_sync_at__gte=since).count()
    invalid = PkuPortalSession.objects.filter(invalid=True).count()
    detail = (f'{bound} bound; last {RECENT_DAYS} days: {logged_in} logged in, '
              f'{synced} imported; {invalid} stored session(s) invalid')
    if logged_in and not synced:
        return ('WARN', 'portal sync health',
                f'{detail}: logins succeed but no portal import did, so the portal data '
                f'endpoints may have changed (server log: "portal endpoint answered 404")')
    return ('OK', 'portal sync health', detail)


def _iaaa_check() -> tuple[str, str, str]:
    try:
        response = requests.get(IAAA_OAUTH_URL, timeout=CONFIG.timeout, allow_redirects=False)
    except requests.RequestException as exc:
        return ('FAIL', 'IAAA reachable', f'unreachable ({exc.__class__.__name__})')
    if response.status_code < 400:
        return ('OK', 'IAAA reachable', f'oauth page answers {response.status_code}')
    return ('WARN', 'IAAA reachable', f'oauth page answers {response.status_code}')
