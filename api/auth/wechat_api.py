"""
微信小程序服务端 API 辅助函数。
用于获取微信小程序的 access_token，并缓存供调用API时使用。
"""
import logging

import requests
from django.core.cache import cache

from api.config import CONFIG

logger = logging.getLogger(__name__)

WX_ACCESS_TOKEN_CACHE_KEY = "wx_miniapp_access_token"
# 提前 5 分钟刷新，避免临界过期
ACCESS_TOKEN_REFRESH_BUFFER = 300


class WechatAPIError(ValueError):
    """
    WeChat answered with a non-zero ``errcode``.

    Subclasses ``ValueError`` so existing callers keep working. ``errcode``
    lets diagnostics such as ``deploy_check --online`` report the code alone,
    without the message or any credential.
    """

    def __init__(self, message: str, errcode: int | str):
        super().__init__(message)
        self.errcode = errcode


def get_wechat_access_token() -> str:
    """
    获取微信小程序 access_token。

    使用 Django cache 缓存，有效期内复用。access_token 有效期 2 小时，
    建议提前刷新，此处缓存时预留 5 分钟缓冲。

    Returns:
        access_token 字符串

    Raises:
        WechatAPIError: 微信接口返回 errcode（ValueError 子类，带 ``errcode``）
        ValueError: 未配置 appid/secret、无法访问或未返回 access_token
    """
    token = cache.get(WX_ACCESS_TOKEN_CACHE_KEY)
    if token:
        return token

    try:
        appid = CONFIG.appid
        secret = CONFIG.secret
    except Exception as exc:
        logger.error("wx_miniapp appid/secret is not configured: %s", exc)
        raise ValueError("服务器未配置微信小程序") from exc

    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": appid,
        "secret": secret,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("get access_token request failed: %s", exc)
        raise ValueError("无法访问微信接口") from exc

    errcode = data.get("errcode")
    if errcode:
        errmsg = data.get("errmsg", "未知错误")
        logger.error(
            "get access_token failed: errcode=%s errmsg=%s", errcode, errmsg)
        raise WechatAPIError(f"微信接口错误: {errmsg}", errcode) from None

    token = data.get("access_token")
    if not token:
        raise ValueError("微信接口未返回 access_token")

    expires_in = data.get("expires_in", 7200)
    cache_timeout = max(expires_in - ACCESS_TOKEN_REFRESH_BUFFER, 60)
    cache.set(WX_ACCESS_TOKEN_CACHE_KEY, token, timeout=cache_timeout)

    return token
