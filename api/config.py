"""
Configuration helpers for API layer.

Covers the mini program (wx) login flow, the subscribe-message templates
used by class reminders (``timetable/README.md`` §6.1) and the share
assets of the timetable poster (§8.5).
"""
from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = [
    "WXMiniappConfig",
    "CONFIG",
    "DEFAULT_SUBSCRIBE_FIELDS",
    "DEFAULT_SUBSCRIBE_PAGE",
    "DEFAULT_SHARE_PAGE",
    "DEFAULT_SHARE_SLOGAN",
    "get_subscribe_template",
    "get_share_config",
]

# Semantic field -> WeChat template key, used when a template omits "fields".
DEFAULT_SUBSCRIBE_FIELDS = {
    "course": "thing1",
    "time": "time2",
    "location": "thing3",
    "note": "thing4",
}
DEFAULT_SUBSCRIBE_PAGE = "pages/timetable/index"
DEFAULT_SHARE_PAGE = "pages/timetable/index"
DEFAULT_SHARE_SLOGAN = "元培智慧书院 · YPPF"

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
    binding_max_failed_attempts = LazySetting(
        "binding_max_failed_attempts", int, default=5
    )
    ticket_ttl_seconds = LazySetting("ticket_ttl_seconds", int, default=60)
    # Subscribe-message templates: {key: {"id", "fields", "page"}}. An empty
    # "id" disables that template (see get_subscribe_template).
    subscribe_templates = LazySetting("subscribe_templates", default={}, type=dict)
    # Share assets of the timetable poster (timetable/README.md §8.5): the
    # page the mini-program code opens, the code's env_version, the
    # official-account QR code (absolute URL or a path under MEDIA_URL;
    # empty → none) and the poster slogan.
    share_miniapp_page = LazySetting(
        "share/miniapp_page", default=DEFAULT_SHARE_PAGE, type=str)
    share_env_version = LazySetting("share/env_version", default="release", type=str)
    share_official_qrcode_url = LazySetting(
        "share/official_qrcode_url", default="", type=str)
    share_slogan = LazySetting("share/slogan", default=DEFAULT_SHARE_SLOGAN, type=str)


CONFIG = WXMiniappConfig(ROOT_CONFIG, "wx_miniapp")


def get_share_config() -> dict:
    """
    The ``wx_miniapp.share`` block with defaults filled in:
    ``{"miniapp_page", "env_version", "official_qrcode_url", "slogan"}``.
    """
    return {
        "miniapp_page": str(CONFIG.share_miniapp_page or DEFAULT_SHARE_PAGE).strip(),
        "env_version": str(CONFIG.share_env_version or "release").strip(),
        "official_qrcode_url": str(CONFIG.share_official_qrcode_url or "").strip(),
        "slogan": str(CONFIG.share_slogan or DEFAULT_SHARE_SLOGAN).strip(),
    }


def get_subscribe_template(key: str) -> dict | None:
    """
    The subscribe-message template ``key`` of ``wx_miniapp.subscribe_templates``
    as ``{"id", "fields", "page"}`` with defaults filled in, or ``None`` when
    the key is absent or its ``id`` is empty (the channel is then disabled
    and clients must not call ``wx.requestSubscribeMessage``).
    """
    templates = CONFIG.subscribe_templates
    raw = templates.get(key) if isinstance(templates, dict) else None
    if not isinstance(raw, dict):
        return None
    template_id = str(raw.get("id") or "").strip()
    if not template_id:
        return None
    fields = raw.get("fields")
    if not isinstance(fields, dict) or not fields:
        fields = DEFAULT_SUBSCRIBE_FIELDS
    page = str(raw.get("page") or DEFAULT_SUBSCRIBE_PAGE).strip()
    return {
        "id": template_id,
        "fields": {str(name): str(value) for name, value in fields.items()},
        "page": page,
    }
