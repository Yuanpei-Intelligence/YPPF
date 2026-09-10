"""
Client of the PKU portal's public-query application
(``portal.pku.edu.cn/publicQuery``), which the portal's 我的课表 / 我的成绩
tiles open since the ``portal2017/bizcenter`` data endpoints went away (they
answered 404 on 2026-09-10).

A :class:`PortalClient` wraps exactly one ``requests.Session`` whose cookie
jar *is* the portal session. It is created either by
:meth:`PortalClient.login` (IAAA application ``portalPublicQuery`` → SSO →
cookies) or by :meth:`PortalClient.from_cookies` (cookies restored from the
encrypted vault kept by :mod:`pku_account.services`). Cookies stored for the
old ``portal2017`` application are not a publicQuery session: they fail as an
expired session and the student logs in again.

Once the session is gone the portal answers a ``*.do`` call with its HTML
login page, a redirect to IAAA or HTTP 401 instead of JSON; all of them are
:class:`PortalSessionExpired`. HTTP 404 is :class:`PortalEndpointMissing`
(the endpoint moved; the session is fine). Network failures and 5xx answers
are :class:`PortalUnreachable`.

Never log cookies or tokens; the cookie names alone are harmless but the
values are the session.
"""
from __future__ import annotations

import logging
import random
from urllib.parse import urlsplit

import requests

from pku_account.config import CONFIG
from pku_account.extern.iaaa import (
    PORTAL_APP_ID,
    PORTAL_APP_NAME,
    PORTAL_SSO,
    PortalUnreachable,
    check_second_factor,
    cookie_matches_host,
    iaaa_login,
    new_session,
    url_host,
)

__all__ = [
    'PORTAL_HOST',
    'PORTAL_BASE',
    'PORTAL_TERMS_URL',
    'PORTAL_COURSE_URL',
    'PORTAL_SCORE_URL',
    'PortalSessionExpired',
    'PortalEndpointMissing',
    'PortalUnreachable',
    'PortalClient',
]

PORTAL_HOST = 'portal.pku.edu.cn'
PORTAL_BASE = f'https://{PORTAL_HOST}/publicQuery'
PORTAL_TERMS_URL = f'{PORTAL_BASE}/ctrl/topic/myCourseTable/getXndXqList.do'
PORTAL_COURSE_URL = f'{PORTAL_BASE}/ctrl/topic/myCourseTable/getCourseInfo.do'
PORTAL_SCORE_URL = f'{PORTAL_BASE}/ctrl/topic/myScore/retrScores.do'
_IAAA_HOST = 'iaaa.pku.edu.cn'
_SESSION_EXPIRED_MESSAGE = '门户会话已失效，请重新登录'
_ENDPOINT_MISSING_MESSAGE = '北京大学信息门户的接口已变更，暂时无法自动获取；课表可先使用粘贴导入'

logger = logging.getLogger(__name__)


class PortalSessionExpired(Exception):
    """The portal answered with its login page / IAAA redirect / 401, not JSON."""


class PortalEndpointMissing(PortalUnreachable):
    """
    The portal answered 404 for a data endpoint: it was removed or moved.

    A subclass of :class:`PortalUnreachable` so every caller already maps it
    to a temporary failure without invalidating the stored session.
    """


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
        Log in through IAAA (application ``portalPublicQuery``) and establish
        the portal session.

        Raises:
            IaaaError (incl. OtpRequired / CaptchaRequired): IAAA rejected
                the credentials, or its pre-check demands a second factor
                (then no password was posted).
            PortalUnreachable: IAAA / portal not reachable, or the SSO step
                did not yield a portal session.
        """
        client = cls()
        check_second_factor(
            client._session, PORTAL_APP_ID, username, timeout=client._timeout,
        )
        token = iaaa_login(
            client._session, username, password, appid=PORTAL_APP_ID,
            redir_url=PORTAL_SSO, app_name=PORTAL_APP_NAME,
            timeout=client._timeout,
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
            if cookie_matches_host(cookie, PORTAL_HOST)
        }

    # ---- data -------------------------------------------------------------

    def get_terms(self) -> dict:
        """
        ``getXndXqList.do``: the account's terms and the current one,
        ``{"success": true, "nowXnxq": {"xndxq": "26-27-1", ...},
        "xndxq": [{"xndxq": "26-27-1", ...}, ...]}``.
        """
        return self._get_json(PORTAL_TERMS_URL)

    def get_course_info(self, term_code: str) -> dict:
        """``getCourseInfo.do`` (我的课表) for a term code such as ``26-27-1``."""
        return self._get_json(PORTAL_COURSE_URL, params={'xndxq': term_code})

    def get_scores(self) -> dict:
        """``retrScores.do`` (我的成绩): every recorded score of the account."""
        return self._get_json(PORTAL_SCORE_URL)

    def ping(self) -> bool:
        """
        Cheap liveness probe (``getXndXqList.do``): ``True`` iff the portal
        still answers JSON for this session. Never raises; any failure counts
        as ``False``.
        """
        try:
            self._get_json(PORTAL_TERMS_URL)
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
            # A live session on a removed endpoint (portal2017's bizcenter
            # course/score endpoints went this way on 2026-09-10). Not a
            # session problem: invalidating the session would only send the
            # student into a re-login loop.
            logger.warning('portal endpoint answered 404: %s', urlsplit(url).path)
            raise PortalEndpointMissing(_ENDPOINT_MISSING_MESSAGE)
        if response.status_code == 401:
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        if url_host(getattr(response, 'url', '') or '') == _IAAA_HOST:
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        try:
            payload = response.json()
        except ValueError as exc:
            # The HTML login page (or anything else that is not JSON).
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE) from exc
        if not isinstance(payload, dict):
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        return payload
