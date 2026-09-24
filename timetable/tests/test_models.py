"""Model tests: term arithmetic across boundaries, current(), section times."""
from datetime import date, time

from django.db import IntegrityError, transaction
from django.test import TestCase

from utils.models.semester import Semester
from timetable.models import AcademicTerm, TimetableEntry, default_section_times
from timetable.tests.helpers import WEEK1_MONDAY, make_entry, make_person, make_term


class AcademicTermTests(TestCase):

    def setUp(self):
        self.term = make_term()  # 26-27-1, week 1 from 2026-09-14

    def test_week_of_across_boundaries(self):
        self.assertEqual(self.term.week_of(date(2026, 9, 14)), 1)
        self.assertEqual(self.term.week_of(date(2026, 9, 20)), 1)
        self.assertEqual(self.term.week_of(date(2026, 9, 21)), 2)
        self.assertEqual(self.term.week_of(date(2026, 9, 13)), 0)
        self.assertEqual(self.term.week_of(date(2026, 9, 7)), 0)
        self.assertEqual(self.term.week_of(date(2026, 9, 6)), -1)
        self.assertEqual(self.term.week_of(date(2027, 1, 3)), 16)
        self.assertEqual(self.term.week_of(date(2027, 1, 4)), 17)
        self.assertFalse(self.term.contains_week(17))
        self.assertFalse(self.term.contains_week(0))
        self.assertTrue(self.term.contains_week(16))

    def test_date_of(self):
        self.assertEqual(self.term.date_of(1, 1), date(2026, 9, 14))
        self.assertEqual(self.term.date_of(1, 7), date(2026, 9, 20))
        self.assertEqual(self.term.date_of(2, 1), date(2026, 9, 21))
        self.assertEqual(self.term.date_of(16, 5), date(2027, 1, 1))
        self.assertEqual(self.term.date_of(0, 1), date(2026, 9, 7))
        self.assertEqual(self.term.end_date(), date(2027, 1, 3))
        self.assertEqual(self.term.week_dates(3)[0], date(2026, 9, 28))
        self.assertEqual(len(self.term.week_dates(3)), 7)

    def test_week_of_and_date_of_round_trip(self):
        for week in range(-2, 20):
            for weekday in range(1, 8):
                on = self.term.date_of(week, weekday)
                self.assertEqual(self.term.week_of(on), week)
                self.assertEqual(on.isoweekday(), weekday)

    def test_clamp_week(self):
        self.assertEqual(self.term.clamp_week(0), 1)
        self.assertEqual(self.term.clamp_week(-3), 1)
        self.assertEqual(self.term.clamp_week(9), 9)
        self.assertEqual(self.term.clamp_week(99), 16)

    def test_yppf_year_semester(self):
        self.assertEqual(self.term.yppf_year_semester(), (2026, Semester.FALL))
        self.assertEqual(AcademicTerm(code='26-27-2').yppf_year_semester(), (2026, Semester.SPRING))
        self.assertIsNone(AcademicTerm(code='26-27-3').yppf_year_semester())
        self.assertEqual(AcademicTerm(code='2026-2027-1').yppf_year_semester(), (2026, Semester.FALL))
        self.assertIsNone(AcademicTerm(code='garbage').yppf_year_semester())
        self.assertIsNone(AcademicTerm(code='').yppf_year_semester())

    def test_current_and_upcoming(self):
        spring = make_term(code='25-26-2', week1_monday=date(2026, 2, 23))
        make_term(code='26-27-9', week1_monday=date(2026, 9, 21), is_active=False)
        self.assertEqual(AcademicTerm.current(date(2026, 9, 13)), spring)
        self.assertEqual(AcademicTerm.current(date(2026, 9, 14)), self.term)
        self.assertEqual(AcademicTerm.current(date(2026, 10, 1)), self.term)
        self.assertIsNone(AcademicTerm.current(date(2026, 1, 1)))
        self.assertEqual(AcademicTerm.upcoming(date(2026, 9, 1)), self.term)
        self.assertEqual(AcademicTerm.upcoming(date(2026, 1, 1)), spring)
        self.assertIsNone(AcademicTerm.upcoming(date(2026, 12, 1)))

    def test_default_section_times(self):
        table = default_section_times()
        self.assertEqual(len(table), 12)
        self.assertEqual(table['1'], ['08:00', '08:50'])
        self.assertEqual(table['12'], ['20:40', '21:30'])
        self.assertEqual(self.term.section_times, table)

    def test_section_time(self):
        self.assertEqual(self.term.section_time(1), (time(8, 0), time(8, 50)))
        self.assertEqual(self.term.section_time(5), (time(13, 0), time(13, 50)))
        self.assertEqual(self.term.section_time(12), (time(20, 40), time(21, 30)))
        # Out-of-table sections clamp to the table bounds.
        self.assertEqual(self.term.section_time(13), (time(20, 40), time(21, 30)))
        self.assertEqual(self.term.section_time(0), (time(8, 0), time(8, 50)))
        self.term.section_times = {}
        self.assertIsNone(self.term.section_time(1))
        self.term.section_times = {'1': ['bad']}
        self.assertIsNone(self.term.section_time(1))


class TimetableEntryTests(TestCase):

    def setUp(self):
        self.term = make_term()
        _, self.person = make_person()

    def test_occurs_in_week_with_parity(self):
        entry = make_entry(self.person, self.term, week_start=2, week_end=5, parity=1)
        self.assertEqual([w for w in range(1, 8) if entry.occurs_in_week(w)], [3, 5])
        entry.parity = TimetableEntry.Parity.EVEN
        self.assertEqual([w for w in range(1, 8) if entry.occurs_in_week(w)], [2, 4])
        entry.parity = TimetableEntry.Parity.ALL
        self.assertEqual([w for w in range(1, 8) if entry.occurs_in_week(w)], [2, 3, 4, 5])

    def test_kind_and_times(self):
        entry = make_entry(self.person, self.term, start_section=3, end_section=4)
        self.assertEqual(entry.kind, 'course')
        self.assertEqual(entry.start_time, time(10, 10))
        self.assertEqual(entry.end_time, time(12, 0))
        # kind follows category, not the source (README §8.1).
        manual = make_entry(self.person, self.term, source=TimetableEntry.Source.MANUAL)
        self.assertEqual((manual.category, manual.kind), ('course', 'course'))
        self.assertTrue(manual.is_manual())
        manual.category = TimetableEntry.Category.OTHER
        self.assertEqual(manual.kind, 'custom')
        manual.category = TimetableEntry.Category.EXAM
        self.assertEqual(manual.kind, 'exam')
        self.assertEqual((manual.role, manual.tag, manual.catalog_entry), ('enrolled', '', None))
        self.assertEqual(entry.start_at(WEEK1_MONDAY).hour, 10)

    def test_unique_key_per_person_term_source(self):
        make_entry(self.person, self.term, external_key='k1')
        make_entry(self.person, self.term, external_key='k1', source=TimetableEntry.Source.PASTE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_entry(self.person, self.term, external_key='k1')

    def test_check_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_entry(self.person, self.term, weekday=8)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_entry(self.person, self.term, week_start=5, week_end=2)
