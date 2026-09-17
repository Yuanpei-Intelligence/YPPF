"""
Fernet helpers protecting the stored portal cookie jar.

The key is ``pku_portal.session_key`` when configured, otherwise
``urlsafe_b64(sha256(SECRET_KEY))``. Rotating either value makes existing
``PkuPortalSession`` rows undecryptable; ``services.get_client`` treats that
as an invalid session so the user simply logs in again.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from pku_account.config import CONFIG

__all__ = ['InvalidToken', 'get_fernet', 'encrypt_json', 'decrypt_json']


def _derived_key() -> bytes:
    # sha256 yields exactly the 32 bytes a Fernet key must encode.
    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    """
    Build the Fernet instance for the configured key.

    Raises:
        ImproperlyConfigured: ``pku_portal.session_key`` is set but is not a
            valid Fernet key.
    """
    configured = CONFIG.session_key
    if configured:
        try:
            return Fernet(configured.encode('utf-8'))
        except ValueError as exc:
            raise ImproperlyConfigured(
                'pku_portal.session_key must be a urlsafe-base64 Fernet key '
                '(32 bytes); generate one with Fernet.generate_key()'
            ) from exc
    return Fernet(_derived_key())


def encrypt_json(obj: Any) -> bytes:
    """Serialize ``obj`` as compact JSON and encrypt it; returns the token."""
    payload = json.dumps(
        obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
    )
    return get_fernet().encrypt(payload.encode('utf-8'))


def decrypt_json(data: bytes | memoryview) -> Any:
    """
    Decrypt a token produced by :func:`encrypt_json` and parse the JSON.

    Raises:
        cryptography.fernet.InvalidToken: wrong key or corrupted data.
    """
    plaintext = get_fernet().decrypt(bytes(data))
    return json.loads(plaintext.decode('utf-8'))
