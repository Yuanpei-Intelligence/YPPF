"""
WeChat mini-program server API: subscribe messages.

``send_subscribe_message`` posts to ``cgi-bin/message/subscribe/send`` with
the server access token cached by ``api.auth.wechat_api``. It never raises
for configuration, network or malformed-response problems (the caller gets
``(False, -1, message)`` instead) and never logs the access token or the
``openid``. Known WeChat error codes are exported as constants.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from django.core.cache import cache

__all__ = [
    'SUBSCRIBE_SEND_URL',
    'REQUEST_TIMEOUT',
    'ERR_OK',
    'ERR_LOCAL',
    'ERR_ACCESS_TOKEN_INVALID',
    'ERR_INVALID_OPENID',
    'ERR_PAGE_INVALID',
    'ERR_ACCESS_TOKEN_EXPIRED',
    'ERR_USER_REFUSED',
    'ERR_TEMPLATE_DATA_INVALID',
    'ACCESS_TOKEN_ERRCODES',
    'send_subscribe_message',
]

logger = logging.getLogger(__name__)

SUBSCRIBE_SEND_URL = 'https://api.weixin.qq.com/cgi-bin/message/subscribe/send'
REQUEST_TIMEOUT = 5

ERR_OK = 0
# Not a WeChat code: configuration, network or response failure on our side.
ERR_LOCAL = -1
ERR_ACCESS_TOKEN_INVALID = 40001
ERR_INVALID_OPENID = 40003
ERR_PAGE_INVALID = 41030
ERR_ACCESS_TOKEN_EXPIRED = 42001
# The user refused the template or has no accepted grant left.
ERR_USER_REFUSED = 43101
ERR_TEMPLATE_DATA_INVALID = 47003
ACCESS_TOKEN_ERRCODES = frozenset({ERR_ACCESS_TOKEN_INVALID, ERR_ACCESS_TOKEN_EXPIRED})


def _normalise_data(data: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    # WeChat wants {"key": {"value": "..."}}; accept plain values as well.
    normalised: dict[str, dict[str, str]] = {}
    for key, value in (data or {}).items():
        if isinstance(value, dict) and 'value' in value:
            normalised[str(key)] = {'value': str(value['value'])}
        else:
            normalised[str(key)] = {'value': str(value)}
    return normalised


def send_subscribe_message(openid: str, template_id: str, page: str,
                           data: dict[str, Any] | None, *,
                           miniprogram_state: str = 'formal',
                           lang: str = 'zh_CN') -> tuple[bool, int, str]:
    """
    Send one subscribe message to ``openid``.

    ``data`` maps template keys to values (plain or ``{"value": ...}``);
    ``page`` is the mini-program page opened on tap (omitted when blank).
    Returns ``(ok, errcode, errmsg)``: ``errcode`` is WeChat's code (``0``
    on success) or ``ERR_LOCAL`` when the request could not be made or
    answered. An invalid or expired access token clears the cached token so
    the next call fetches a fresh one.
    """
    from api.auth.wechat_api import WX_ACCESS_TOKEN_CACHE_KEY, get_wechat_access_token
    try:
        token = get_wechat_access_token()
    except ValueError as exc:
        logger.warning('subscribe message not sent: %s', exc)
        return False, ERR_LOCAL, str(exc)
    payload: dict[str, Any] = {
        'touser': openid,
        'template_id': template_id,
        'data': _normalise_data(data),
        'miniprogram_state': miniprogram_state,
        'lang': lang,
    }
    if page:
        payload['page'] = page
    try:
        response = requests.post(
            SUBSCRIBE_SEND_URL, params={'access_token': token},
            json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        # The exception text may embed the request URL (and so the access
        # token); log the class only.
        logger.warning('subscribe message request failed: %s', type(exc).__name__)
        return False, ERR_LOCAL, f'request failed: {type(exc).__name__}'
    try:
        result = response.json()
    except ValueError:
        logger.warning('subscribe message: non-JSON response (HTTP %s)',
                       response.status_code)
        return False, ERR_LOCAL, f'invalid response (HTTP {response.status_code})'
    if not isinstance(result, dict):
        logger.warning('subscribe message: unexpected response shape')
        return False, ERR_LOCAL, 'invalid response'
    try:
        errcode = int(result.get('errcode') or 0)
    except (TypeError, ValueError):
        errcode = ERR_LOCAL
    errmsg = str(result.get('errmsg') or '')
    if errcode == ERR_OK:
        return True, ERR_OK, errmsg or 'ok'
    if errcode in ACCESS_TOKEN_ERRCODES:
        cache.delete(WX_ACCESS_TOKEN_CACHE_KEY)
    level = logging.INFO if errcode == ERR_USER_REFUSED else logging.WARNING
    logger.log(level, 'subscribe message failed: errcode=%s errmsg=%s template=%s',
               errcode, errmsg, template_id)
    return False, errcode, errmsg
