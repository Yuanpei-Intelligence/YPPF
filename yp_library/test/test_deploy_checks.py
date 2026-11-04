"""Tests of ``yp_library/deploy_checks.py`` with a fake ``pymssql``."""
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from utils.deploy_check import FAIL, OK, WARN
from yp_library import deploy_checks as plugin


DATABASE_ENV = {
    'LIB_DB_HOST': 'lib.example',
    'LIB_DB_USER': 'reader',
    'LIB_DB_PASSWORD': 'hunter2',
    'LIB_DB': 'books',
}
LIBRARY_CONFIG = SimpleNamespace(
    organization_name='书房', start_time='07:00', end_time='23:00')


class LibraryDeployChecksTests(SimpleTestCase):
    def test_library_config(self):
        config = SimpleNamespace(
            organization_name='书房', start_time='07:00', end_time='')
        with patch.object(plugin, 'CONFIG', config):
            missing = plugin._check_library_config()
            config.end_time = '23:00'
            complete = plugin._check_library_config()
        self.assertEqual(missing, (
            FAIL, 'library',
            'missing library.open_time_end: library pages and API fail'))
        self.assertEqual(complete[0], OK)

    def test_unset_environment_is_reported_by_name_and_not_probed(self):
        with patch.dict(os.environ), \
                patch.object(plugin, 'CONFIG', LIBRARY_CONFIG), \
                patch.object(plugin, '_check_database_connection') as connect:
            for name in plugin.DATABASE_ENV:
                os.environ.pop(name, None)
            os.environ.update(LIB_DB_HOST='lib.example', LIB_DB_PASSWORD='hunter2')
            results = list(plugin.checks(online=True))
        connect.assert_not_called()
        self.assertEqual(results[1], (
            WARN, 'library database',
            'LIB_DB_USER, LIB_DB unset in this environment: the hourly '
            'update_lib_data job fails'))
        self.assertNotIn('hunter2', repr(results))

    def test_connection_is_probed_only_online(self):
        probe_result = (OK, 'library database connection', '')
        with patch.dict(os.environ, DATABASE_ENV), \
                patch.object(plugin, 'CONFIG', LIBRARY_CONFIG), \
                patch.object(plugin, '_check_database_connection',
                             return_value=probe_result) as connect:
            offline = list(plugin.checks())
            connect.assert_not_called()
            online = list(plugin.checks(online=True))
        connect.assert_called_once_with()
        self.assertEqual(offline[1], (OK, 'library database', 'LIB_DB_* set'))
        self.assertEqual(len(online), len(offline) + 1)

    def test_connection_failure_reports_the_error_class_only(self):
        fake = ModuleType('pymssql')
        fake.Error = type('Error', (Exception,), {})
        fake.connect = MagicMock(
            side_effect=fake.Error('Login failed for user reader (hunter2)'))
        with patch.dict(sys.modules, {'pymssql': fake}), \
                patch.dict(os.environ, DATABASE_ENV):
            failed = plugin._check_database_connection()
            conn = MagicMock()
            fake.connect = MagicMock(return_value=conn)
            connected = plugin._check_database_connection()

        self.assertEqual(
            failed, (FAIL, 'library database connection', 'cannot connect (Error)'))
        self.assertEqual(
            connected, (OK, 'library database connection', 'connected'))
        fake.connect.assert_called_once_with(
            server='lib.example', user='reader', password='hunter2',
            database='books', login_timeout=5)
        conn.close.assert_called_once_with()
