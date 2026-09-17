"""Tests of the timetable deployment checks (``timetable/deploy_checks.py``, README §9)."""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase

from timetable import deploy_checks
from timetable.models import AcademicTerm


def _by_name(results):
    return {name: (level, detail) for level, name, detail in results}


class TimetableDeployChecksTests(TestCase):

    def test_levels_are_valid_tuples(self):
        results = list(deploy_checks.checks())
        self.assertTrue(results)
        for item in results:
            self.assertEqual(len(item), 3)
            self.assertIn(item[0], ('OK', 'WARN', 'FAIL'))

    def test_missing_term_fails(self):
        results = _by_name(deploy_checks.checks())
        self.assertEqual(results['AcademicTerm'][0], 'FAIL')
        self.assertEqual(results['timetable.jobs'][0], 'OK')

    def test_current_term_details_and_warnings(self):
        AcademicTerm.objects.create(
            code='26-27-1', name='fall', week1_monday=date.today() - timedelta(days=7),
            total_weeks=19, exam_week_start=17)
        results = _by_name(deploy_checks.checks())
        self.assertNotIn('AcademicTerm', results)
        level, detail = results['term (current)']
        self.assertEqual(level, 'OK')
        self.assertIn('26-27-1 weeks=19 exam_week_start=17', detail)
        self.assertEqual(results['term 26-27-1 catalog'][0], 'WARN')
        self.assertEqual(results['term 26-27-1 exams'][0], 'WARN')
        self.assertEqual(results['term 26-27-1 calendar'][0], 'WARN')
        self.assertNotIn('term 26-27-1 exam weeks', results)

    def test_missing_static_qr_fails(self):
        share = {'miniapp_page': 'pages/timetable/index', 'env_version': 'release',
                 'official_qrcode_url': '/static/assets/img/does_not_exist.png', 'slogan': 'x'}
        with mock.patch.object(deploy_checks, 'get_share_config', return_value=share):
            results = _by_name(deploy_checks.checks())
        self.assertEqual(results['wx_miniapp.share.official_qrcode_url'][0], 'FAIL')

    def test_shipped_static_qr_is_found(self):
        share = {'miniapp_page': 'pages/timetable/index', 'env_version': 'release',
                 'official_qrcode_url': '/static/assets/img/yppf_official_qrcode.png', 'slogan': 'x'}
        with mock.patch.object(deploy_checks, 'get_share_config', return_value=share):
            results = _by_name(deploy_checks.checks())
        self.assertEqual(results['wx_miniapp.share.official_qrcode_url'][0], 'OK')

    def test_online_reports_miniapp_code(self):
        with mock.patch('timetable.share.miniapp_code_url', return_value=None):
            results = _by_name(deploy_checks.checks(online=True))
        self.assertEqual(results['poster mini-program code'][0], 'WARN')
        with mock.patch('timetable.share.miniapp_code_url', return_value='http://x/media/a.png'):
            results = _by_name(deploy_checks.checks(online=True))
        self.assertEqual(results['poster mini-program code'][0], 'OK')
        self.assertNotIn('poster mini-program code', _by_name(deploy_checks.checks()))
