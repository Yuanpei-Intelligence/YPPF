"""Tests of the Fernet helpers in ``pku_account.crypto``."""
import base64
import hashlib
import json
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from pku_account import crypto
from pku_account.config import PkuPortalConfig


class CryptoTests(SimpleTestCase):
    def test_roundtrip_with_configured_key(self):
        key = Fernet.generate_key().decode()
        cookies = {'JSESSIONID': 'portal-session', 'route': 'r1'}
        with patch.object(PkuPortalConfig, 'session_key', key):
            token = crypto.encrypt_json(cookies)
            self.assertIsInstance(token, bytes)
            self.assertNotIn(b'portal-session', token)
            self.assertEqual(crypto.decrypt_json(token), cookies)
            # BinaryField may hand back a memoryview on some backends.
            self.assertEqual(crypto.decrypt_json(memoryview(token)), cookies)

    def test_key_is_derived_from_secret_key_when_unset(self):
        with patch.object(PkuPortalConfig, 'session_key', ''):
            token = crypto.encrypt_json({'a': 'b'})
        digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
        derived = Fernet(base64.urlsafe_b64encode(digest))
        self.assertEqual(json.loads(derived.decrypt(token)), {'a': 'b'})

    def test_other_key_cannot_decrypt(self):
        with patch.object(
            PkuPortalConfig, 'session_key', Fernet.generate_key().decode(),
        ):
            token = crypto.encrypt_json({'a': 1})
        with patch.object(
            PkuPortalConfig, 'session_key', Fernet.generate_key().decode(),
        ):
            with self.assertRaises(crypto.InvalidToken):
                crypto.decrypt_json(token)

    def test_malformed_key_is_improperly_configured(self):
        with patch.object(PkuPortalConfig, 'session_key', 'not-a-fernet-key'):
            with self.assertRaises(ImproperlyConfigured):
                crypto.get_fernet()
