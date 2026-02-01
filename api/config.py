"""
Configuration helpers for API layer.

Currently focuses on mini program (wx) login flow.
"""
from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = ["WXMiniappConfig", "CONFIG"]

class WXMiniappConfig(Config):
    """
    Settings for WeChat mini program authentication.
    """

    appid = LazySetting("appid", type=str)
    secret = LazySetting("secret", type=str)
    jscode2session_url = LazySetting(
        "jscode2session_url",
        default="https://api.weixin.qq.com/sns/jscode2session",
        type=str,
    )
    token_expire_minutes = LazySetting("token_expire_minutes", int, default=120)
    signed_openid_ttl_minutes = LazySetting(
        "signed_openid_ttl_minutes", int, default=10
    )
    ticket_ttl_seconds = LazySetting("ticket_ttl_seconds", int, default=60)


CONFIG = WXMiniappConfig(ROOT_CONFIG, "wx_miniapp")

