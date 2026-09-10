"""
IAAA (北京大学统一身份认证) login client.

Pure ``requests`` code, no Django models. One ``oauthlogin.do`` POST returns a
one-time token which an application's ``ssoLogin.do`` exchanges for its own
session: the portal's public-query application (``portalPublicQuery``, see
:mod:`pku_account.extern.portal`) or the course-selection system
(``syllabus``, see :mod:`pku_account.extern.elective`). The flow mirrors
current open-source tools (sshwy/pku3b, zhuozhiyongde/Grade-Huh-Moe).

Security rules of this module:

- The username is never logged together with the password, the token or any
  cookie, and none of those values is placed in an exception message.
- Off-campus logins may require a second factor or a captcha since 2026-03;
  those are reported as :class:`OtpRequired` / :class:`CaptchaRequired` and
  are not solved here. :func:`check_second_factor` asks IAAA before the
  password is posted.
"""
from __future__ import annotations

import logging
import random
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from pku_account.config import CONFIG

__all__ = [
    'IAAA_LOGIN_URL',
    'IAAA_OAUTH_URL',
    'IAAA_AUTHEN_MODE_URL',
    'PORTAL_APP_ID',
    'PORTAL_APP_NAME',
    'PORTAL_SSO',
    'USER_AGENT',
    'PortalUnreachable',
    'IaaaError',
    'OtpRequired',
    'CaptchaRequired',
    'new_session',
    'url_host',
    'cookie_matches_host',
    'classify_iaaa_error',
    'check_second_factor',
    'iaaa_login',
]

IAAA_LOGIN_URL = 'https://iaaa.pku.edu.cn/iaaa/oauthlogin.do'
IAAA_OAUTH_URL = 'https://iaaa.pku.edu.cn/iaaa/oauth.jsp'
IAAA_AUTHEN_MODE_URL = 'https://iaaa.pku.edu.cn/iaaa/isMobileAuthen.do'
# The portal's 我的课表 / 我的成绩 tiles open this application.
PORTAL_APP_ID = 'portalPublicQuery'
PORTAL_APP_NAME = '校内信息门户公共查询'
PORTAL_SSO = 'https://portal.pku.edu.cn/publicQuery/ssoLogin.do'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# Substrings of IAAA's ``errors.msg`` that identify a second-factor demand.
# They are checked before the captcha markers because an SMS code message
# ("短信验证码") is a second factor, not a picture captcha.
_OTP_MARKERS = ('二次', '双因素', 'OTP', '短信')
_CAPTCHA_MARKERS = ('验证码',)
# ``authenMode`` of ``isMobileAuthen.do`` for an account without a second factor.
_NO_SECOND_FACTOR = '否'

logger = logging.getLogger(__name__)


class PortalUnreachable(Exception):
    """IAAA or the portal could not be reached or answered with a 5xx."""


class IaaaError(Exception):
    """
    IAAA rejected the login.

    ``code`` and ``msg`` are IAAA's own values (``errors.code`` /
    ``errors.msg``); ``msg`` is safe to show to the user.
    """

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


class OtpRequired(IaaaError):
    """IAAA demands a second factor (SMS / OTP); not solvable server-side."""


class CaptchaRequired(IaaaError):
    """IAAA demands a captcha; not solvable server-side."""


def new_session() -> requests.Session:
    """A ``requests.Session`` with browser-like default headers."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })
    return session


def url_host(url: str) -> str:
    """The lower-case host of ``url``; ``''`` when it has none or is malformed."""
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def cookie_matches_host(cookie: Any, host: str) -> bool:
    """Whether a cookie-jar entry is sent to ``host`` (its own or a parent domain)."""
    domain = str(getattr(cookie, 'domain', '') or '').lstrip('.').lower()
    if not domain:
        return False
    return domain == host or host.endswith('.' + domain)


def classify_iaaa_error(code: str, msg: str) -> IaaaError:
    """Map an IAAA failure to the most specific :class:`IaaaError` subclass."""
    text = f'{code} {msg}'
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in _OTP_MARKERS):
        return OtpRequired(code, msg)
    if any(marker in text for marker in _CAPTCHA_MARKERS):
        return CaptchaRequired(code, msg)
    return IaaaError(code, msg)


def check_second_factor(
    session: requests.Session,
    appid: str,
    username: str,
    *,
    timeout: float | None = None,
) -> None:
    """
    Ask IAAA (``isMobileAuthen.do``) whether ``username`` must pass a second
    factor for application ``appid``, and log the answer.

    Advisory only, like pku3b does: the meaning of the non-``否`` modes (an
    account setting vs. this network location) is not verified yet, and
    blocking on it could refuse logins IAAA itself would accept from the
    campus server. The login request decides; an IAAA rejection that names a
    second factor is still raised as ``OtpRequired`` by ``iaaa_login``.
    Returns the mode (``None`` when unknown). Never raises.
    """
    if timeout is None:
        timeout = CONFIG.timeout
    params = {
        'appId': appid,
        'userName': username,
        '_rand': f'{random.random():.16f}',
    }
    try:
        response = session.get(
            IAAA_AUTHEN_MODE_URL, params=params, timeout=timeout,
        )
        payload: Any = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.info('IAAA second-factor pre-check skipped: %s',
                    type(exc).__name__)
        return None
    mode = payload.get('authenMode') if isinstance(payload, dict) else None
    if not isinstance(mode, str) or not mode.strip():
        return None
    mode = mode.strip()
    if mode != _NO_SECOND_FACTOR:
        # The mode is a short IAAA enum (e.g. OTP), never an identifier.
        logger.info('IAAA pre-check names a second factor (%s); trying the login anyway', mode[:16])
    return mode


def _oauth_referer(appid: str, redir_url: str, app_name: str) -> str:
    # Header values must be latin-1 encodable, hence the percent-encoding.
    query = urlencode({
        'appID': appid,
        'appName': app_name,
        'redirectUrl': redir_url,
    })
    return f'{IAAA_OAUTH_URL}?{query}'


def iaaa_login(
    session: requests.Session,
    username: str,
    password: str,
    *,
    appid: str = PORTAL_APP_ID,
    redir_url: str = PORTAL_SSO,
    app_name: str = PORTAL_APP_NAME,
    timeout: float | None = None,
) -> str:
    """
    Authenticate against IAAA and return the one-time SSO token.

    Args:
        session: the session that will later be used for the application;
            IAAA's own cookies are kept on it.
        username: IAAA account (student / staff id).
        password: IAAA password; used for this single request only.
        appid: IAAA application id: ``portalPublicQuery`` (the portal, the
            default) or ``syllabus`` (the course-selection system).
        redir_url: the SSO endpoint IAAA knows that application by.
        app_name: the application's display name in the IAAA ``Referer``.
        timeout: seconds; defaults to ``pku_portal.timeout``.

    Raises:
        PortalUnreachable: network failure or 5xx from IAAA.
        CaptchaRequired, OtpRequired, IaaaError: IAAA rejected the login.
    """
    if timeout is None:
        timeout = CONFIG.timeout
    form = {
        'appid': appid,
        'userName': username,
        'password': password,
        'randCode': '',
        'smsCode': '',
        'otpCode': '',
        'redirUrl': redir_url,
    }
    headers = {
        'Referer': _oauth_referer(appid, redir_url, app_name),
        'Origin': 'https://iaaa.pku.edu.cn',
        'X-Requested-With': 'XMLHttpRequest',
    }
    try:
        response = session.post(
            IAAA_LOGIN_URL, data=form, headers=headers, timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning('IAAA login request failed: %s', type(exc).__name__)
        raise PortalUnreachable('无法连接北京大学统一身份认证服务') from exc
    if response.status_code >= 500:
        logger.warning('IAAA answered HTTP %s', response.status_code)
        raise PortalUnreachable('北京大学统一身份认证服务暂时不可用')

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise IaaaError(
            'BAD_RESPONSE', '统一身份认证服务返回了无法解析的响应',
        ) from exc
    if not isinstance(payload, dict):
        raise IaaaError('BAD_RESPONSE', '统一身份认证服务返回了无法解析的响应')

    token = payload.get('token')
    if payload.get('success') is True and token:
        return str(token)

    errors = payload.get('errors')
    if not isinstance(errors, dict):
        errors = {}
    code = str(errors.get('code') or payload.get('code') or 'UNKNOWN')
    msg = str(errors.get('msg') or payload.get('msg') or '统一身份认证登录失败')
    error = classify_iaaa_error(code, msg)
    # The code is IAAA's error class, never an identifier of the user.
    logger.info('IAAA rejected a login: %s (%s)', type(error).__name__, code)
    raise error
