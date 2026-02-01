"""
One-time ticket for webview redirect.
Ticket is stored in cache and invalidated after first use.
"""
import secrets

from django.core.cache import cache
from api.config import CONFIG

WEBVIEW_TICKET_KEY_PREFIX = "wx_webview_ticket:"
WEBVIEW_TICKET_TTL = CONFIG.ticket_ttl_seconds


def create_webview_ticket(user_id: int) -> str:
    """
    Create a one-time ticket for webview redirect.
    Ticket is stored in cache and invalidated after first use.
    """
    ticket = secrets.token_urlsafe(32)
    cache.set(
        f"{WEBVIEW_TICKET_KEY_PREFIX}{ticket}",
        str(user_id),
        timeout=WEBVIEW_TICKET_TTL,
    )
    return ticket


def consume_webview_ticket(ticket: str) -> int | None:
    """
    Validate ticket and return user_id if valid. Deletes ticket from cache (one-time use).
    Returns None if ticket is invalid or already used.
    """
    if not ticket:
        return None
    key = f"{WEBVIEW_TICKET_KEY_PREFIX}{ticket}"
    user_id_str = cache.get(key)
    if user_id_str is None:
        return None
    cache.delete(key)
    try:
        return int(user_id_str)
    except (ValueError, TypeError):
        return None
