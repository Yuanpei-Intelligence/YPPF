"""
Configuration helpers for API layer.

Covers the mini program (wx) login flow and the subscribe-message templates
used by class reminders (``timetable/README.md`` §6.1).
"""
from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = [
    "WXMiniappConfig",
    "CONFIG",
    "DEFAULT_SUBSCRIBE_FIELDS",
    "DEFAULT_SUBSCRIBE_PAGE",
    "get_subscribe_template",
]

# Semantic field -> WeChat template key, used when a template omits "fields".
DEFAULT_SUBSCRIBE_FIELDS = {
    "course": "thing1",
    "time": "time2",
    "location": "thing3",
    "note": "thing4",
}
DEFAULT_SUBSCRIBE_PAGE = "pages/timetable/index"

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


CONFIG = WXMiniappConfig(ROOT_CONFIG, "wx_miniapp")


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
