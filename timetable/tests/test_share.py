"""Share asset tests (``timetable/README.md`` §8.5): file cache and URLs."""
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from timetable import share

CONFIG = {'miniapp_page': 'pages/timetable/index', 'env_version': 'release',
          'official_qrcode_url': '', 'slogan': '元培智慧书院 · YPPF'}


class ShareAssetsTests(SimpleTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = override_settings(MEDIA_ROOT=self.tmp.name, MEDIA_URL='/media/')
        settings.enable()
        self.addCleanup(settings.disable)
        config = patch('timetable.share.get_share_config', return_value=dict(CONFIG))
        self.config = config.start()
        self.addCleanup(config.stop)
        self.cached = Path(self.tmp.name) / 'timetable' / 'share' / 'miniapp_timetable.png'

    def test_fetch_cache_and_expiry(self):
        with patch('timetable.share.fetch_miniapp_code', return_value=b'img-1') as fetch:
            assets = share.share_assets()
            self.assertEqual(assets['slogan'], '元培智慧书院 · YPPF')
            self.assertIsNone(assets['official_qrcode'])
            self.assertTrue(assets['miniapp_qrcode'].endswith(
                '/media/timetable/share/miniapp_timetable.png'))
            self.assertEqual(self.cached.read_bytes(), b'img-1')
            self.assertEqual(share.miniapp_code_url(), assets['miniapp_qrcode'])
            fetch.assert_called_once()
        # An expired file is refreshed.
        old = time.time() - (share.CACHE_DAYS + 1) * 86400
        os.utime(self.cached, (old, old))
        with patch('timetable.share.fetch_miniapp_code', return_value=b'img-2') as fetch:
            share.miniapp_code_url()
            fetch.assert_called_once()
        self.assertEqual(self.cached.read_bytes(), b'img-2')
        # A failed refresh keeps serving the stale file (with a warning).
        os.utime(self.cached, (old, old))
        with patch('timetable.share.fetch_miniapp_code', return_value=None), \
                self.assertLogs('timetable.share', level='WARNING'):
            self.assertIsNotNone(share.miniapp_code_url())
        self.assertEqual(self.cached.read_bytes(), b'img-2')
        # Another scene gets its own file.
        with patch('timetable.share.fetch_miniapp_code', return_value=b'other'):
            url = share.miniapp_code_url('poster')
        self.assertTrue(url.endswith('/media/timetable/share/miniapp_poster.png'))

    def test_failure_without_cache_is_null(self):
        with patch('timetable.share.fetch_miniapp_code', return_value=None):
            self.assertIsNone(share.miniapp_code_url())
            self.assertIsNone(share.share_assets()['miniapp_qrcode'])
        self.assertFalse(self.cached.exists())

    def test_official_qrcode_url(self):
        self.assertIsNone(share.official_qrcode_url())
        self.config.return_value['official_qrcode_url'] = 'https://example.com/oa.png'
        self.assertEqual(share.official_qrcode_url(), 'https://example.com/oa.png')
        self.config.return_value['official_qrcode_url'] = '/timetable/share/oa.png'
        url = share.official_qrcode_url()
        self.assertTrue(url.startswith('http'))
        self.assertTrue(url.endswith('/media/timetable/share/oa.png'))
        self.config.return_value['official_qrcode_url'] = 'oa.png'
        self.assertTrue(share.official_qrcode_url().endswith('/media/oa.png'))
