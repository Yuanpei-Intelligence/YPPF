"""Tests of the pku_account deployment checks (``pku_account/deploy_checks.py``)."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from pku_account import deploy_checks
from pku_account.models import PkuAccount
from pku_account.tests.test_services import make_person


def _by_name(results):
    return {name: (level, detail) for level, name, detail in results}


def _config(**overrides):
    values = {'enabled': True, 'session_key': '', 'timeout': 5}
    values.update(overrides)
    return SimpleNamespace(**values)


class PkuAccountDeployChecksTests(TestCase):

    def _account(self, username, **fields):
        user = make_person(username)
        return PkuAccount.objects.create(
            user=user, pku_username=f'21000{username[-5:]}', verified_at=datetime.now(), **fields)

    def test_offline_checks_make_no_requests(self):
        with mock.patch.object(deploy_checks, 'CONFIG', _config(enabled=False)), \
                mock.patch.object(deploy_checks.requests, 'get') as get:
            results = _by_name(deploy_checks.checks())
        get.assert_not_called()
        self.assertEqual(results['pku_portal.enabled'][0], 'WARN')
        self.assertEqual(results['pku_portal.session_key'], ('OK', 'derived from SECRET_KEY'))
        self.assertEqual(results['portal sync health'][0], 'OK')
        self.assertIn('0 bound', results['portal sync health'][1])
        self.assertNotIn('IAAA reachable', results)

    def test_invalid_session_key_fails(self):
        with mock.patch.object(deploy_checks, 'get_fernet', side_effect=ImproperlyConfigured('x')):
            results = _by_name(deploy_checks.checks())
        self.assertEqual(results['pku_portal.session_key'][0], 'FAIL')

    def test_logins_without_imports_warn(self):
        now = datetime.now()
        self._account('S000101', last_login_at=now - timedelta(days=1))
        self._account('S000102', last_login_at=now - timedelta(days=2),
                      last_sync_at=now - timedelta(days=30))
        level, detail = _by_name(deploy_checks.checks())['portal sync health']
        self.assertEqual(level, 'WARN')
        self.assertIn('2 logged in, 0 imported', detail)

    def test_recent_import_is_healthy(self):
        now = datetime.now()
        self._account('S000103', last_login_at=now - timedelta(days=1),
                      last_sync_at=now - timedelta(hours=3))
        level, detail = _by_name(deploy_checks.checks())['portal sync health']
        self.assertEqual(level, 'OK')
        self.assertIn('1 logged in, 1 imported', detail)

    def test_online_iaaa_redirect_is_reachable(self):
        with mock.patch.object(deploy_checks, 'CONFIG', _config()), \
                mock.patch.object(deploy_checks.requests, 'get',
                                  return_value=SimpleNamespace(status_code=302)) as get:
            results = _by_name(deploy_checks.checks(online=True))
        self.assertEqual(results['IAAA reachable'][0], 'OK')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_online_unreachable_iaaa_fails_without_message(self):
        with mock.patch.object(deploy_checks, 'CONFIG', _config()), \
                mock.patch.object(deploy_checks.requests, 'get',
                                  side_effect=requests.ConnectionError('refused by proxy 10.0.0.1')):
            results = _by_name(deploy_checks.checks(online=True))
        self.assertEqual(results['IAAA reachable'][0], 'FAIL')
        self.assertNotIn('10.0.0.1', results['IAAA reachable'][1])
