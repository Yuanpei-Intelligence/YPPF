"""Tests of ``semester/deploy_checks.py``."""
from datetime import date
from unittest.mock import patch

from django.test import TestCase

from utils.deploy_check import FAIL, OK, WARN
from semester import deploy_checks as plugin
from semester.models import Semester, SemesterType


def debug(enabled: bool):
    return patch('utils.deploy_check.DEBUG', enabled)


class SemesterDeployChecksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fall = SemesterType.objects.create(name='Fall')
        cls.spring = SemesterType.objects.create(name='Spring')

    def add(self, year, kind, start, end):
        return Semester.objects.create(
            year=year, type=kind, start_date=start, end_date=end)

    def test_no_started_semester_breaks_the_homepage(self):
        self.add(2026, self.fall, date(2026, 9, 7), date(2027, 1, 15))
        with debug(False):
            production = plugin._check_semesters(date(2026, 9, 1))
        with debug(True):
            development = plugin._check_semesters(date(2026, 9, 1))
        self.assertEqual(production[0], FAIL)
        self.assertIn('no semester has started', production[2])
        self.assertEqual(development[0], WARN)

    def test_current_upcoming_and_missing_next_semester(self):
        self.add(2025, self.spring, date(2026, 2, 23), date(2026, 7, 5))
        current = plugin._check_semesters(date(2026, 5, 1))
        no_next = plugin._check_semesters(date(2026, 8, 1))
        self.add(2026, self.fall, date(2026, 9, 7), date(2027, 1, 15))
        between = plugin._check_semesters(date(2026, 8, 1))

        self.assertEqual(current, (OK, 'semesters', '2025 Spring covers today'))
        self.assertEqual(no_next[0], WARN)
        self.assertEqual(
            between, (OK, 'semesters', 'between semesters; 2026 Fall starts 2026-09-07'))

    def test_skipped_when_the_database_is_unreachable(self):
        with patch.object(plugin, 'db_connection_healthy', return_value=False):
            results = list(plugin.checks())
        self.assertEqual(results, [(WARN, 'semesters', 'skipped: database unreachable')])
