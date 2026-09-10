"""
Client of the PKU portal (``portal.pku.edu.cn/portal2017``).

A :class:`PortalClient` wraps exactly one ``requests.Session`` whose cookie
jar *is* the portal session. It is created either by
:meth:`PortalClient.login` (IAAA credentials → SSO → cookies) or by
:meth:`PortalClient.from_cookies` (cookies restored from the encrypted vault
kept by :mod:`pku_account.services`).

Once the portal session is gone the portal answers every ``*.do`` call with
its HTML login page (or redirects to IAAA) instead of JSON; both are reported
as :class:`PortalSessionExpired`. Network failures and 5xx answers are
:class:`PortalUnreachable`.

Never log cookies or tokens; the cookie names alone are harmless but the
values are the session.
"""
from __future__ import annotations

import logging
import random
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import requests

from pku_account.config import CONFIG
from pku_account.extern.iaaa import (
    PORTAL_SSO,
    PortalUnreachable,
    iaaa_login,
    new_session,
)

__all__ = [
    'PORTAL_HOST',
    'PORTAL_BASE',
    'PORTAL_COURSE_URL',
    'PORTAL_SCORE_URL',
    'PortalSessionExpired',
    'PortalEndpointMissing',
    'PortalUnreachable',
    'PortalClient',
    'guess_term_code',
]

PORTAL_HOST = 'portal.pku.edu.cn'
PORTAL_BASE = f'https://{PORTAL_HOST}/portal2017'
PORTAL_COURSE_URL = f'{PORTAL_BASE}/bizcenter/course/getCourseInfo.do'
PORTAL_SCORE_URL = f'{PORTAL_BASE}/bizcenter/score/retrScores.do'
_IAAA_HOST = 'iaaa.pku.edu.cn'
_SESSION_EXPIRED_MESSAGE = '门户会话已失效，请重新登录'
_ENDPOINT_MISSING_MESSAGE = '北京大学信息门户的接口已变更，暂时无法自动获取；课表可先使用粘贴导入'

logger = logging.getLogger(__name__)


class PortalSessionExpired(Exception):
    """The portal answered with its login page / IAAA redirect, not JSON."""


class PortalEndpointMissing(PortalUnreachable):
    """
    The portal answered 404 for a data endpoint: it was removed or moved.

    A subclass of :class:`PortalUnreachable` so every caller already maps it
    to a temporary failure without invalidating the stored session.
    """


def guess_term_code(on: date | None = None) -> str:
    """
    Best-effort portal term code (``xndxq``) for a date: ``YY-YY-1`` for
    September–January, ``-2`` for February–June, ``-3`` for July–August.
    Only used by the liveness probe, where a wrong term is harmless.
    """
    if on is None:
        on = date.today()
    if on.month >= 9:
        start, suffix = on.year, 1
    elif on.month == 1:
        start, suffix = on.year - 1, 1
    elif on.month <= 6:
        start, suffix = on.year - 1, 2
    else:
        start, suffix = on.year - 1, 3
    return f'{start % 100:02d}-{(start + 1) % 100:02d}-{suffix}'


def _is_portal_cookie(cookie: Any) -> bool:
    domain = str(getattr(cookie, 'domain', '') or '').lstrip('.').lower()
    if not domain:
        return False
    return domain == PORTAL_HOST or PORTAL_HOST.endswith('.' + domain)


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


class PortalClient:
    """One portal session; see the module docstring for the lifecycle."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: float | None = None,
    ):
        self._session = session if session is not None else new_session()
        self._timeout = CONFIG.timeout if timeout is None else timeout

    # ---- construction -----------------------------------------------------

    @classmethod
    def login(cls, username: str, password: str) -> 'PortalClient':
        """
        Log in through IAAA and establish the portal session.

        Raises:
            IaaaError (incl. OtpRequired / CaptchaRequired): IAAA rejected
                the credentials.
            PortalUnreachable: IAAA / portal not reachable, or the SSO step
                did not yield a portal session.
        """
        client = cls()
        token = iaaa_login(
            client._session, username, password, timeout=client._timeout,
        )
        params = {'_rand': f'{random.random():.16f}', 'token': token}
        try:
            response = client._session.get(
                PORTAL_SSO, params=params, timeout=client._timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.warning('portal SSO request failed: %s', type(exc).__name__)
            raise PortalUnreachable('无法连接北京大学信息门户') from exc
        if response.status_code >= 500:
            logger.warning('portal SSO answered HTTP %s', response.status_code)
            raise PortalUnreachable('北京大学信息门户暂时不可用')
        if not client.cookies():
            logger.warning('portal SSO completed without a session cookie')
            raise PortalUnreachable('北京大学信息门户未能建立会话，请稍后再试')
        return client

    @classmethod
    def from_cookies(cls, cookies: dict[str, str]) -> 'PortalClient':
        """Rebuild a client from a cookie mapping returned by :meth:`cookies`."""
        client = cls()
        for name, value in cookies.items():
            client._session.cookies.set(
                str(name), str(value), domain=PORTAL_HOST, path='/',
            )
        return client

    # ---- session ----------------------------------------------------------

    def cookies(self) -> dict[str, str]:
        """The portal cookies (name → value); IAAA's own cookies are dropped."""
        return {
            cookie.name: cookie.value
            for cookie in self._session.cookies
            if _is_portal_cookie(cookie)
        }

    # ---- data -------------------------------------------------------------

    def get_course_info(self, term_code: str) -> dict:
        """``getCourseInfo.do`` for a term code such as ``26-27-1``."""
        return self._get_json(PORTAL_COURSE_URL, params={'xndxq': term_code})

    def get_scores(self) -> dict:
        """``retrScores.do``: every recorded score of the account."""
        return self._get_json(PORTAL_SCORE_URL)

    def ping(self, term_code: str | None = None) -> bool:
        """
        Cheap liveness probe: ``True`` iff the portal still answers JSON for
        this session. Never raises; any failure counts as ``False``.
        """
        if term_code is None:
            term_code = guess_term_code()
        try:
            self._get_json(PORTAL_COURSE_URL, params={'xndxq': term_code})
        except (PortalSessionExpired, PortalUnreachable):
            return False
        except Exception:  # noqa: BLE001 - a probe must never raise
            logger.warning('portal ping failed unexpectedly', exc_info=True)
            return False
        return True

    # ---- internals --------------------------------------------------------

    def _get_json(
        self, url: str, params: dict[str, str] | None = None,
    ) -> dict:
        try:
            response = self._session.get(
                url, params=params, timeout=self._timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.warning('portal request failed: %s', type(exc).__name__)
            raise PortalUnreachable('无法连接北京大学信息门户') from exc
        if response.status_code >= 500:
            logger.warning('portal answered HTTP %s', response.status_code)
            raise PortalUnreachable('北京大学信息门户暂时不可用')
        if response.status_code == 404:
            # A live session on a removed endpoint (bizcenter course/score went
            # this way on 2026-09-10). Not a session problem: invalidating the
            # session would only send the student into a re-login loop.
            logger.warning('portal endpoint answered 404: %s', urlsplit(url).path)
            raise PortalEndpointMissing(_ENDPOINT_MISSING_MESSAGE)
        if _host_of(getattr(response, 'url', '') or '') == _IAAA_HOST:
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        try:
            payload = response.json()
        except ValueError as exc:
            # The HTML login page (or anything else that is not JSON).
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE) from exc
        if not isinstance(payload, dict):
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        return payload
