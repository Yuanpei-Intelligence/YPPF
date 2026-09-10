"""Tests of the pku_account deployment checks (``pku_account/deploy_checks.py``)."""
from types import SimpleNamespace
from unittest import mock

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from pku_account import deploy_checks
from pku_account.extern.iaaa import IAAA_OAUTH_URL
from pku_account.extern.portal import PORTAL_COURSE_URL, PORTAL_SCORE_URL


def _by_name(results):
    return {name: (level, detail) for level, name, detail in results}


def _config(**overrides):
    values = {'enabled': True, 'session_key': '', 'timeout': 5}
    values.update(overrides)
    return SimpleNamespace(**values)


class PkuAccountDeployChecksTests(TestCase):

    def test_offline_checks(self):
        with mock.patch.object(deploy_checks, 'CONFIG', _config(enabled=False)), \
                mock.patch.object(deploy_checks.requests, 'get') as get:
            results = _by_name(deploy_checks.checks())
        get.assert_not_called()
        self.assertEqual(results['pku_portal.enabled'][0], 'WARN')
        self.assertEqual(results['pku_portal.session_key'], ('OK', 'derived from SECRET_KEY'))
        self.assertIn('bound=0', results['pku accounts'][1])
        self.assertNotIn('IAAA reachable', results)

    def test_invalid_session_key_fails(self):
        with mock.patch.object(deploy_checks, 'get_fernet', side_effect=ImproperlyConfigured('x')):
            results = _by_name(deploy_checks.checks())
        self.assertEqual(results['pku_portal.session_key'][0], 'FAIL')

    def test_online_detects_removed_endpoints(self):
        statuses = {IAAA_OAUTH_URL: 200, PORTAL_COURSE_URL: 404, PORTAL_SCORE_URL: 302}

        def fake_get(url, **kwargs):
            return SimpleNamespace(status_code=statuses[url])

        with mock.patch.object(deploy_checks, 'CONFIG', _config()), \
                mock.patch.object(deploy_checks.requests, 'get', side_effect=fake_get):
            results = _by_name(deploy_checks.checks(online=True))
        self.assertEqual(results['IAAA reachable'][0], 'OK')
        self.assertEqual(results['portal course endpoint'][0], 'FAIL')
        self.assertIn('404', results['portal course endpoint'][1])
        self.assertEqual(results['portal score endpoint'][0], 'OK')

    def test_online_unreachable_iaaa_fails(self):
        with mock.patch.object(deploy_checks, 'CONFIG', _config()), \
                mock.patch.object(deploy_checks.requests, 'get',
                                  side_effect=requests.ConnectionError('refused')):
            results = _by_name(deploy_checks.checks(online=True))
        self.assertEqual(results['IAAA reachable'][0], 'FAIL')
        self.assertNotIn('refused', results['IAAA reachable'][1])
        self.assertEqual(results['portal course endpoint'][0], 'WARN')
