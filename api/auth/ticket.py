"""Database-backed, atomic one-time tickets for WebView login."""

import hashlib
import secrets
from datetime import datetime, timedelta

from django.db import transaction

from api.config import CONFIG
from generic.models import PendingWebviewTicket

WEBVIEW_TICKET_TTL = CONFIG.ticket_ttl_seconds
_EXPIRED_TICKET_CLEANUP_BATCH_SIZE = 100


def _ticket_digest(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def create_webview_ticket(user_id: int) -> str:
    """Create a random ticket while storing only its digest and purpose."""
    now = datetime.now()
    ticket = secrets.token_urlsafe(32)
    with transaction.atomic():
        expired_digests = list(
            PendingWebviewTicket.objects.filter(expires_at__lte=now)
            .order_by("token_digest")
            .values_list("token_digest", flat=True)[
                :_EXPIRED_TICKET_CLEANUP_BATCH_SIZE
            ]
        )
        for token_digest in expired_digests:
            try:
                expired = (
                    PendingWebviewTicket.objects.select_for_update().get(
                        token_digest=token_digest
                    )
                )
            except PendingWebviewTicket.DoesNotExist:
                continue
            if expired.expires_at <= now:
                expired.delete()
        PendingWebviewTicket.objects.create(
            token_digest=_ticket_digest(ticket),
            user_id=user_id,
            purpose=PendingWebviewTicket.Purpose.WEBVIEW_LOGIN,
            expires_at=now + timedelta(seconds=WEBVIEW_TICKET_TTL),
        )
    return ticket


def consume_webview_ticket(ticket: str) -> int | None:
    """Atomically consume a valid WebView-login ticket and return its user ID."""
    if not isinstance(ticket, str) or not ticket:
        return None
    now = datetime.now()
    with transaction.atomic():
        try:
            pending = PendingWebviewTicket.objects.select_for_update().get(
                token_digest=_ticket_digest(ticket)
            )
        except PendingWebviewTicket.DoesNotExist:
            return None
        if (
            pending.expires_at <= now
            or pending.purpose
            != PendingWebviewTicket.Purpose.WEBVIEW_LOGIN
        ):
            pending.delete()
            return None
        user_id = pending.user_id
        pending.delete()
    return user_id
