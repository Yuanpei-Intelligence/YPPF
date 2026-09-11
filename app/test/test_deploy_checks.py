"""Tests of ``app/deploy_checks.py`` with mocked configuration."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from utils.deploy_check import FAIL, OK, WARN
from generic.models import User
from questionnaire.models import Survey
from app import deploy_checks as plugin
from app.models import NaturalPerson, Organization


def debug(enabled: bool):
    return patch('utils.deploy_check.DEBUG', enabled)


class _Unresolvable:
    """A config section whose every setting fails to resolve."""

    def __getattr__(self, name):
        raise ImproperlyConfigured(f'{name} should be float')


def make_config(**course_overrides):
    course = dict(
        yx_election_start='2026-09-01 10:00:00',
        yx_election_end='2026-09-02 10:00:00',
        publish_time='2026-09-03 10:00:00',
        btx_election_start='2026-09-04 10:00:00',
        btx_election_end='2026-09-05 10:00:00',
        audit_teachers=['T0001'],
        prerequisite_survey={'enabled': False},
    )
    course.update(course_overrides)
    yqpoint = SimpleNamespace(
        signin_points=[1, 2, [2, 4]],
        org_name='元气值中心',
        activity=SimpleNamespace(invalid_hour=12.0, per_hour=1.0, max=10),
    )
    return SimpleNamespace(course=SimpleNamespace(**course), yqpoint=yqpoint)


class AppDeployChecksTests(TestCase):
    def use_config(self, config):
        # course_survey_utils holds its own reference to the same CONFIG.
        self.enterContext(patch.object(plugin, 'CONFIG', config))
        self.enterContext(patch('app.course_survey_utils.CONFIG', config))
        return config

    def create_survey(self, title):
        if not hasattr(self, 'survey_owner'):
            self.survey_owner = User.objects.create_user(
                'deploy-check-survey-owner', 'Owner', password='pw')
        return Survey.objects.create(
            title=title, creator=self.survey_owner,
            start_time=datetime(2026, 9, 1), end_time=datetime(2026, 9, 30))

    def test_election_windows_in_order(self):
        self.use_config(make_config())
        self.assertEqual(
            plugin._check_election_windows(datetime(2026, 8, 31)),
            (OK, 'course election windows',
             'ordered; next is course.yx_election_start at 2026-09-01 10:00'))
        self.assertEqual(
            plugin._check_election_windows(datetime(2026, 9, 10)),
            (OK, 'course election windows', 'ordered; all in the past'))

    def test_future_stage_later_than_its_successor_fails(self):
        self.use_config(make_config(publish_time='2026-09-20 20:00:00'))
        # Once every stage is past, register_selection() schedules them now,
        # in order, so historical misordering is harmless.
        self.assertEqual(plugin._check_election_windows(datetime(2026, 9, 30))[0], OK)
        level, _, detail = plugin._check_election_windows(datetime(2026, 8, 31))
        self.assertEqual(level, FAIL)
        self.assertIn('course.publish_time (2026-09-20 20:00) is later than '
                      'course.btx_election_start (2026-09-04 10:00)', detail)

    def test_missing_or_unparseable_window_fails(self):
        self.use_config(make_config(
            yx_election_start=None, btx_election_end='next Friday'))
        level, _, detail = plugin._check_election_windows(datetime(2026, 8, 31))
        self.assertEqual(level, FAIL)
        self.assertIn('course.yx_election_start, course.btx_election_end missing '
                      'or not a time', detail)

    def test_yqpoint_rewards(self):
        config = self.use_config(make_config())
        self.assertEqual(
            plugin._check_yqpoint_rewards(),
            (OK, 'YQPoint rewards', '3-day sign-in cycle'))
        for points in ([], [[4, 2]], [1, 'two'], [True], [[1, 2, 3]], 5):
            with self.subTest(points=points):
                config.yqpoint.signin_points = points
                self.assertEqual(plugin._check_yqpoint_rewards()[0], FAIL)
        config.yqpoint.signin_points = [1]
        config.yqpoint.activity = _Unresolvable()
        level, _, detail = plugin._check_yqpoint_rewards()
        self.assertEqual(level, FAIL)
        self.assertIn('YQPoint.activity.invalid_hour', detail)

    def test_first_auditor_must_match_one_teacher(self):
        self.use_config(make_config())
        manager = NaturalPerson.objects
        with patch.object(manager, 'get_teacher',
                          side_effect=NaturalPerson.DoesNotExist):
            with debug(False):
                production = plugin._check_auditors()
            with debug(True):
                development = plugin._check_auditors()
        with patch.object(manager, 'get_teacher') as get_teacher:
            found = plugin._check_auditors()

        self.assertEqual(production[0], FAIL)
        self.assertIn('DoesNotExist', production[2])
        self.assertNotIn('T0001', production[2])
        self.assertEqual(development[0], WARN)
        self.assertEqual(found, (OK, 'course.auditors',
                                 '1 configured; the first matches a teacher'))
        get_teacher.assert_called_once_with('T0001')
        self.use_config(make_config(audit_teachers=[]))
        self.assertEqual(plugin._check_auditors()[0], FAIL)

    def test_prerequisite_survey_titles_must_resolve(self):
        self.use_config(make_config(prerequisite_survey={
            'enabled': True,
            'rules': [{'pattern': '^26', 'survey': 'Freshman survey'}],
            'fallback': 'General survey',
        }))
        self.create_survey('General survey')
        freshman_missing = plugin._check_prerequisite_survey()
        self.create_survey('Freshman survey')
        resolved = plugin._check_prerequisite_survey()
        Survey.objects.filter(title='General survey').delete()
        fallback_missing = plugin._check_prerequisite_survey()

        self.assertEqual(freshman_missing[0], FAIL)
        self.assertIn("'Freshman survey'", freshman_missing[2])
        self.assertEqual(resolved, (OK, 'course.prerequisite_survey',
                                    'enabled; all 2 survey title(s) resolve'))
        self.assertEqual(fallback_missing[0], FAIL)
        self.assertIn("'General survey'", fallback_missing[2])

    def test_prerequisite_survey_shape_errors_fail_closed(self):
        self.use_config(make_config())
        self.assertEqual(plugin._check_prerequisite_survey(),
                         (OK, 'course.prerequisite_survey', 'disabled'))
        self.use_config(make_config(prerequisite_survey={
            'enabled': True,
            'rules': [{'pattern': '(', 'survey': 'Survey'}],
            'fallback': 'Fallback',
        }))
        self.assertEqual(plugin._check_prerequisite_survey(), (
            FAIL, 'course.prerequisite_survey',
            'Invalid course survey regular expression: course selection fails closed'))
        self.use_config(make_config(prerequisite_survey={'enabled': 'yes'}))
        self.assertEqual(plugin._check_prerequisite_survey()[0], FAIL)

    def test_yqpoint_organization_must_exist(self):
        self.use_config(make_config())
        with patch.object(Organization.objects, 'filter') as filter_orgs, \
                debug(False):
            filter_orgs.return_value.exists.return_value = False
            missing = plugin._check_yqpoint_organization()
            filter_orgs.return_value.exists.return_value = True
            found = plugin._check_yqpoint_organization()
        filter_orgs.assert_called_with(oname='元气值中心')
        self.assertEqual(missing[0], FAIL)
        self.assertEqual(found[0], OK)

    def test_database_checks_are_skipped_when_unreachable(self):
        self.use_config(make_config())
        with patch.object(plugin, 'db_connection_healthy', return_value=False):
            results = list(plugin.checks())
        self.assertEqual(
            [name for _, name, _ in results],
            ['course election windows', 'YQPoint rewards', 'course and YQPoint data'])
