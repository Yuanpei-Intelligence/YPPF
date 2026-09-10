"""Tests of ``Appointment/deploy_checks.py`` with mocked configuration."""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from utils.deploy_check import FAIL, OK, WARN
from Appointment import deploy_checks as plugin


def debug(enabled: bool):
    return patch('utils.deploy_check.DEBUG', enabled)


class _MalformedStart:
    @property
    def semester_start(self):
        raise ValueError('2023-13-45')


class AppointmentDeployChecksTests(SimpleTestCase):
    def check_token(self, token):
        with patch.object(plugin, 'CONFIG', SimpleNamespace(display_token=token)):
            return plugin._check_display_token()

    def check_start(self, config, today=date(2026, 9, 10)):
        with patch.object(plugin, 'CONFIG', config):
            return plugin._check_semester_start(today)

    def test_display_token(self):
        with debug(False):
            for token in (None, '', '   ', '$TOKEN$'):
                with self.subTest(token=token):
                    self.assertEqual(self.check_token(token)[0], FAIL)
            not_a_string = self.check_token(123)
            real = self.check_token('display-secret')
        with debug(True):
            development = self.check_token(None)

        self.assertEqual(not_a_string[0], FAIL)
        self.assertEqual(real, (OK, 'underground.token.display', 'set'))
        self.assertEqual(development[0], WARN)

    def test_semester_start(self):
        stale = SimpleNamespace(semester_start=datetime(2023, 2, 20))
        with debug(False):
            current = self.check_start(
                SimpleNamespace(semester_start=datetime(2026, 9, 7)))
            production = self.check_start(stale)
            missing = self.check_start(SimpleNamespace(semester_start=None))
            malformed = self.check_start(_MalformedStart())
        with debug(True):
            development = self.check_start(stale)

        self.assertEqual(
            current, (OK, 'underground.semester_data.semester_start', '2026-09-07'))
        self.assertEqual(production[0], FAIL)
        self.assertIn('2023-02-20 is 1298 days ago', production[2])
        self.assertEqual(development[0], WARN)
        self.assertEqual(missing[0], FAIL)
        self.assertEqual(malformed[0], FAIL)
        self.assertNotIn('2023-13-45', malformed[2])
