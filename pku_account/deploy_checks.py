"""
Deployment checks of the pku_account app, run by ``python manage.py deploy_check``.

Offline: the feature switch, the key that encrypts stored portal sessions and
the number of bound accounts. Online: IAAA reachability and whether the portal
data endpoints the importers call still exist — on 2026-09-10 the portal had
removed ``bizcenter/course/getCourseInfo.do`` and ``bizcenter/score/retrScores.do``
and answered 404 for them, which silently broke the server-side import. An
endpoint that exists answers an unauthenticated request with a login page or
a redirect instead.
"""
from __future__ import annotations

from typing import Iterator

import requests
from django.core.exceptions import ImproperlyConfigured

from pku_account.config import CONFIG
from pku_account.crypto import get_fernet
from pku_account.extern.iaaa import IAAA_OAUTH_URL
from pku_account.extern.portal import PORTAL_COURSE_URL, PORTAL_SCORE_URL
from pku_account.models import PkuAccount, PkuPortalSession

__all__ = ['checks']


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

    yield ('OK', 'pku accounts',
           f'bound={PkuAccount.objects.count()} stored sessions={PkuPortalSession.objects.count()}')

    if online:
        yield _iaaa_check()
        yield _endpoint_check('portal course endpoint', PORTAL_COURSE_URL)
        yield _endpoint_check('portal score endpoint', PORTAL_SCORE_URL)


def _iaaa_check() -> tuple[str, str, str]:
    try:
        response = requests.get(IAAA_OAUTH_URL, timeout=CONFIG.timeout)
    except requests.RequestException as exc:
        return ('FAIL', 'IAAA reachable', f'unreachable ({exc.__class__.__name__})')
    if response.status_code == 200:
        return ('OK', 'IAAA reachable', 'oauth page answers 200')
    return ('WARN', 'IAAA reachable', f'oauth page answers {response.status_code}')


def _endpoint_check(name: str, url: str) -> tuple[str, str, str]:
    try:
        response = requests.get(url, timeout=CONFIG.timeout, allow_redirects=False)
    except requests.RequestException as exc:
        return ('WARN', name, f'unreachable ({exc.__class__.__name__})')
    if response.status_code == 404:
        return ('FAIL', name,
                'answers 404: the portal removed this endpoint, so the server-side '
                'import fails until the fetcher is updated (paste import still works)')
    return ('OK', name, f'present (unauthenticated request answers {response.status_code})')
