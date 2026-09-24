"""Tests of the ``timetable_seed_terms`` management command."""
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from semester.models import Semester, SemesterType
from timetable.models import AcademicTerm


class SeedTermsCommandTests(TestCase):

    def setUp(self):
        fall = SemesterType.objects.create(name='秋季')
        spring = SemesterType.objects.create(name='春季')
        odd = SemesterType.objects.create(name='寒假')
        Semester.objects.create(year=2026, type=fall,
                                start_date=date(2026, 9, 16),    # a Wednesday
                                end_date=date(2027, 1, 15))
        Semester.objects.create(year=2026, type=spring,
                                start_date=date(2027, 2, 22),    # a Monday
                                end_date=date(2027, 6, 30))
        Semester.objects.create(year=2026, type=odd,
                                start_date=date(2027, 1, 16), end_date=date(2027, 2, 21))

    def run_command(self, *args):
        out = StringIO()
        call_command('timetable_seed_terms', *args, stdout=out)
        return out.getvalue()

    def test_creates_terms_from_semesters(self):
        output = self.run_command()
        self.assertIn('created 2, existing 0, skipped 1', output)
        fall = AcademicTerm.objects.get(code='26-27-1')
        self.assertEqual(fall.week1_monday, date(2026, 9, 14))
        self.assertEqual(fall.name, '2026-2027学年秋季学期')
        self.assertEqual(fall.total_weeks, 16)
        self.assertTrue(fall.is_active)
        spring = AcademicTerm.objects.get(code='26-27-2')
        self.assertEqual(spring.week1_monday, date(2027, 2, 22))
        self.assertEqual(spring.name, '2026-2027学年春季学期')
        self.assertEqual(AcademicTerm.objects.count(), 2)

    def test_idempotent_and_keeps_existing_rows(self):
        self.run_command('--total-weeks', '18')
        fall = AcademicTerm.objects.get(code='26-27-1')
        self.assertEqual(fall.total_weeks, 18)
        fall.name = '手工改名'
        fall.week1_monday = date(2026, 9, 21)
        fall.save()
        output = self.run_command()
        self.assertIn('created 0, existing 2, skipped 1', output)
        fall.refresh_from_db()
        self.assertEqual(fall.name, '手工改名')
        self.assertEqual(fall.week1_monday, date(2026, 9, 21))
        self.assertEqual(fall.total_weeks, 18)
        self.assertEqual(AcademicTerm.objects.count(), 2)
