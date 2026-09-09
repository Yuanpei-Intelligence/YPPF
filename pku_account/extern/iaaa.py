"""
IAAA (北京大学统一身份认证) login client.

Pure ``requests`` code, no Django models. Mirrors the public flow used by
pkuhelper-web-score and Packup-Android: one ``oauthlogin.do`` POST returns a
one-time token which ``portal.pku.edu.cn/portal2017/ssoLogin.do`` exchanges
for the portal session (see :mod:`pku_account.extern.portal`).

Security rules of this module:

- The username is never logged together with the password, the token or any
  cookie, and none of those values is placed in an exception message.
- Off-campus logins may require a second factor or a captcha since 2026-03;
  those are reported as :class:`OtpRequired` / :class:`CaptchaRequired` and
  are not solved here.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import requests

from pku_account.config import CONFIG

__all__ = [
    'IAAA_LOGIN_URL',
    'IAAA_OAUTH_URL',
    'PORTAL_SSO',
    'USER_AGENT',
    'PortalUnreachable',
    'IaaaError',
    'OtpRequired',
    'CaptchaRequired',
    'new_session',
    'classify_iaaa_error',
    'iaaa_login',
]

IAAA_LOGIN_URL = 'https://iaaa.pku.edu.cn/iaaa/oauthlogin.do'
IAAA_OAUTH_URL = 'https://iaaa.pku.edu.cn/iaaa/oauth.jsp'
PORTAL_SSO = 'https://portal.pku.edu.cn/portal2017/ssoLogin.do'
PORTAL_APP_NAME = '北京大学校内信息门户新版'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# Substrings of IAAA's ``errors.msg`` that identify a second-factor demand.
# They are checked before the captcha markers because an SMS code message
# ("短信验证码") is a second factor, not a picture captcha.
_OTP_MARKERS = ('二次', '双因素', 'OTP', '短信')
_CAPTCHA_MARKERS = ('验证码',)

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


def classify_iaaa_error(code: str, msg: str) -> IaaaError:
    """Map an IAAA failure to the most specific :class:`IaaaError` subclass."""
    text = f'{code} {msg}'
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in _OTP_MARKERS):
        return OtpRequired(code, msg)
    if any(marker in text for marker in _CAPTCHA_MARKERS):
        return CaptchaRequired(code, msg)
    return IaaaError(code, msg)


def _oauth_referer(appid: str, redir_url: str) -> str:
    # Header values must be latin-1 encodable, hence the percent-encoding.
    query = urlencode({
        'appID': appid,
        'appName': PORTAL_APP_NAME,
        'redirectUrl': redir_url,
    })
    return f'{IAAA_OAUTH_URL}?{query}'


def iaaa_login(
    session: requests.Session,
    username: str,
    password: str,
    *,
    appid: str = 'portal2017',
    redir_url: str = PORTAL_SSO,
    timeout: float | None = None,
) -> str:
    """
    Authenticate against IAAA and return the one-time SSO token.

    Args:
        session: the session that will later be used for the portal; IAAA's
            own cookies are kept on it.
        username: IAAA account (student / staff id).
        password: IAAA password; used for this single request only.
        appid: IAAA application id, ``portal2017`` for the portal.
        redir_url: the SSO endpoint of that application.
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
        'Referer': _oauth_referer(appid, redir_url),
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
