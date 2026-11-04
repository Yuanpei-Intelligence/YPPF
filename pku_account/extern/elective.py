"""
Client of the PKU course-selection system (选课系统,
``elective.pku.edu.cn/elective2008``).

Used as the fallback source of a student's lessons while the portal course
table is still empty (``timetable/README.md`` §3.1, §4.4):
:meth:`ElectiveClient.login` signs in through IAAA (application ``syllabus``)
and :meth:`ElectiveClient.get_results_html` returns the 选课结果 page for
``timetable.sources.pku_parsers.parse_elective_table``. The session is never
stored; one client serves one import request.

Errors follow :mod:`pku_account.extern.portal`: network failures and 5xx
answers are :class:`PortalUnreachable`, HTTP 404 is
:class:`PortalEndpointMissing`, and a redirect to IAAA or to a login page, a
time-out page or HTTP 401 is :class:`PortalSessionExpired`.

Never log tokens, cookies, passwords or page content.
"""
from __future__ import annotations

import logging
import random
import re
from urllib.parse import urlsplit

import requests

from pku_account.config import CONFIG
from pku_account.extern.iaaa import (
    PortalUnreachable,
    check_second_factor,
    cookie_matches_host,
    iaaa_login,
    new_session,
    url_host,
)
from pku_account.extern.portal import PortalEndpointMissing, PortalSessionExpired

__all__ = [
    'ELECTIVE_HOST',
    'ELECTIVE_BASE',
    'ELECTIVE_APP_ID',
    'ELECTIVE_APP_NAME',
    'ELECTIVE_OAUTH_REDIR',
    'ELECTIVE_SSO',
    'ELECTIVE_HELP_URL',
    'ELECTIVE_RESULTS_URL',
    'ElectiveClient',
]

ELECTIVE_HOST = 'elective.pku.edu.cn'
ELECTIVE_BASE = f'https://{ELECTIVE_HOST}/elective2008'
ELECTIVE_APP_ID = 'syllabus'
ELECTIVE_APP_NAME = '学生选课系统'
# The redirect URL IAAA knows the application by: plain http, explicit port.
ELECTIVE_OAUTH_REDIR = f'http://{ELECTIVE_HOST}:80/elective2008/ssoLogin.do'
ELECTIVE_SSO = f'{ELECTIVE_BASE}/ssoLogin.do'
ELECTIVE_HELP_URL = (
    f'{ELECTIVE_BASE}/edu/pku/stu/elective/controller/help/HelpController.jpf')
ELECTIVE_RESULTS_URL = (
    f'{ELECTIVE_BASE}/edu/pku/stu/elective/controller/electiveWork/showResults.do')

_IAAA_HOST = 'iaaa.pku.edu.cn'
# Links of the dual-degree chooser: ssoLogin.do?sida=<32 hex>&sttp=bzx|bfx.
_SIDA_RE = re.compile(r'[?&]sida=([0-9A-Za-z]{32})&(?:amp;)?sttp=(?:bzx|bfx)')
# ``sttp`` of the main degree (主修); ``bfx`` is the minor / double degree.
_MAIN_DEGREE = 'bzx'
_CATEGORY_ERROR_MARKER = '用户选课类别ERR'
# Text of the "not logged in / timed out" page. Only trusted on a page that
# lacks the results table, because help texts may quote it.
_EXPIRED_MARKERS = ('尚未登录', '会话超时', '登录超时')
_RESULTS_MARKER = 'datagrid'
_SESSION_EXPIRED_MESSAGE = '选课系统会话已失效，请重新登录'
_NO_SESSION_MESSAGE = '北京大学选课系统未能建立会话，请稍后再试'
_ENDPOINT_MISSING_MESSAGE = '北京大学选课系统的页面已变更，暂时无法自动获取选课结果'

logger = logging.getLogger(__name__)


def _redirected_to_login(requested_url: str, response) -> bool:
    # The redirects ended on IAAA, or on a page other than the requested one
    # whose path names a login page.
    final_url = str(getattr(response, 'url', '') or '')
    if not final_url:
        return False
    if url_host(final_url) == _IAAA_HOST:
        return True
    final_path = urlsplit(final_url).path
    return (final_path != urlsplit(requested_url).path
            and 'login' in final_path.lower())


class ElectiveClient:
    """One course-selection session; see the module docstring."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: float | None = None,
    ):
        self._session = session if session is not None else new_session()
        self._timeout = CONFIG.timeout if timeout is None else timeout

    @classmethod
    def login(cls, username: str, password: str) -> 'ElectiveClient':
        """
        Log in through IAAA (application ``syllabus``) and establish the
        course-selection session. A dual-degree student is shown a chooser
        first; the client continues as the main degree (主修).

        Raises:
            IaaaError (incl. OtpRequired / CaptchaRequired): IAAA rejected
                the credentials, or its pre-check demands a second factor
                (then no password was posted).
            PortalEndpointMissing: the SSO endpoint answered 404.
            PortalUnreachable: IAAA / the site not reachable, or the SSO step
                did not yield a session.
        """
        client = cls()
        check_second_factor(
            client._session, ELECTIVE_APP_ID, username, timeout=client._timeout,
        )
        token = iaaa_login(
            client._session, username, password, appid=ELECTIVE_APP_ID,
            redir_url=ELECTIVE_OAUTH_REDIR, app_name=ELECTIVE_APP_NAME,
            timeout=client._timeout,
        )
        params = {'_rand': f'{random.random():.16f}', 'token': token}
        try:
            response = client._get(
                ELECTIVE_SSO, params=params,
                headers={'Referer': f'{ELECTIVE_BASE}/'},
            )
            body = response.text or ''
            if _CATEGORY_ERROR_MARKER in body:
                logger.warning('elective SSO did not recognise the selection category')
                raise PortalUnreachable('北京大学选课系统无法识别该账号的选课类别')
            chooser = _SIDA_RE.search(body)
            if chooser is not None:
                # Dual degree: continue as the main degree (主修).
                referer = str(getattr(response, 'url', '') or ELECTIVE_SSO)
                client._get(
                    ELECTIVE_SSO,
                    params={'sida': chooser.group(1), 'sttp': _MAIN_DEGREE},
                    headers={'Referer': referer},
                )
        except PortalSessionExpired as exc:
            logger.warning('elective SSO was sent back to a login page')
            raise PortalUnreachable(_NO_SESSION_MESSAGE) from exc
        if not client._has_session():
            logger.warning('elective SSO completed without a session cookie')
            raise PortalUnreachable(_NO_SESSION_MESSAGE)
        return client

    def get_results_html(self) -> str:
        """
        The 选课结果 page (``showResults.do``) as HTML. The help page is
        visited first, as the site's own navigation does, and is sent as the
        ``Referer``.

        Raises:
            PortalSessionExpired: the session is gone (IAAA / login redirect,
                401, or the time-out page instead of the results table).
            PortalEndpointMissing: a page answered 404.
            PortalUnreachable: the site could not be reached.
        """
        self._get(ELECTIVE_HELP_URL)
        response = self._get(
            ELECTIVE_RESULTS_URL, headers={'Referer': ELECTIVE_HELP_URL},
        )
        text = response.text or ''
        if (_RESULTS_MARKER not in text
                and any(marker in text for marker in _EXPIRED_MARKERS)):
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        return text

    # ---- internals --------------------------------------------------------

    def _has_session(self) -> bool:
        return any(cookie_matches_host(cookie, ELECTIVE_HOST)
                   for cookie in self._session.cookies)

    def _get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        try:
            response = self._session.get(
                url, params=params, headers=headers, timeout=self._timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.warning('elective request failed: %s', type(exc).__name__)
            raise PortalUnreachable('无法连接北京大学选课系统') from exc
        if response.status_code >= 500:
            logger.warning('elective answered HTTP %s', response.status_code)
            raise PortalUnreachable('北京大学选课系统暂时不可用')
        if response.status_code == 404:
            logger.warning('elective endpoint answered 404: %s', urlsplit(url).path)
            raise PortalEndpointMissing(_ENDPOINT_MISSING_MESSAGE)
        if response.status_code == 401 or _redirected_to_login(url, response):
            raise PortalSessionExpired(_SESSION_EXPIRED_MESSAGE)
        return response
