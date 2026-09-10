"""Tests of the ``timetable_check`` deployment checklist command (README §9)."""
from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from timetable.models import AcademicTerm


class TimetableCheckCommandTests(TestCase):

    def test_missing_term_fails(self):
        out = StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command('timetable_check', stdout=out)
        self.assertIn('AcademicTerm', str(ctx.exception))
        text = out.getvalue()
        self.assertIn('[FAIL] AcademicTerm', text)
        self.assertIn('[OK] migrations', text)
        self.assertIn('checks, 1 failed', text)

    def test_warn_only_reports_term_details(self):
        AcademicTerm.objects.create(
            code='26-27-1', name='fall', week1_monday=date.today() - timedelta(days=7),
            total_weeks=19, exam_week_start=17)
        out = StringIO()
        call_command('timetable_check', '--warn-only', stdout=out)
        text = out.getvalue()
        self.assertIn('[OK] term (current): 26-27-1 weeks=19 exam_week_start=17', text)
        self.assertIn('[WARN] term 26-27-1 catalog', text)
        self.assertIn('[WARN] term 26-27-1 exams', text)
        self.assertIn('[OK] timetable.jobs', text)
        self.assertIn('wx_miniapp.share.official_qrcode_url', text)
        self.assertIn('0 failed', text)
