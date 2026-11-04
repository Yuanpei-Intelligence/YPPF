from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from semester.calendar import (
    calendar_between,
    effective_weekday,
    events_between,
    is_class_day,
)
from semester.models import CalendarEvent, Semester, SemesterType
from semester.api import semester_of


class SemesterTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        type1 = SemesterType.objects.create(name='test1')
        s1 = Semester.objects.create(
            year=2020, type=type1, start_date=date(2020, 2, 1), end_date=date(2020, 6, 30))
        type2 = SemesterType.objects.create(name='test2')
        s2 = Semester.objects.create(
            year=2020, type=type2, start_date=date(2020, 9, 1), end_date=date(2021, 1, 1))
        cls.semesters = [s1, s2]

    def test_semester_api(self):
        # Test Exception
        try:
            _ = semester_of(date(2020, 1, 1))
            _ = semester_of(date(2020, 7, 1), allow_fallback=False)
            raise Exception('Should raise DoesNotExist')
        except Semester.DoesNotExist:
            pass

        s1, s2 = self.semesters
        # Test hit
        self.assertEqual(s1, semester_of(date(2020, 3, 1)))

        # Test fallback
        self.assertEqual(s1, semester_of(date(2020, 8, 20)))
        self.assertEqual(s2, semester_of(date(2021, 1, 15)))


def make_event(kind, start, end=None, name='事件', follows_weekday=None, note=''):
    return CalendarEvent.objects.create(
        kind=kind, start_date=start, end_date=end or start, name=name,
        follows_weekday=follows_weekday, note=note)


class CalendarEventModelTests(TestCase):

    def test_clean_rules(self):
        reversed_dates = CalendarEvent(
            kind='holiday', start_date=date(2026, 10, 7), end_date=date(2026, 10, 1), name='x')
        with self.assertRaises(ValidationError) as ctx:
            reversed_dates.full_clean()
        self.assertEqual(set(ctx.exception.message_dict), {'end_date'})

        swap_without_weekday = CalendarEvent(
            kind='swap', start_date=date(2026, 10, 10), end_date=date(2026, 10, 10), name='x')
        with self.assertRaises(ValidationError) as ctx:
            swap_without_weekday.full_clean()
        self.assertEqual(set(ctx.exception.message_dict), {'follows_weekday'})

        info_with_weekday = CalendarEvent(
            kind='info', start_date=date(2026, 10, 10), end_date=date(2026, 10, 10),
            name='x', follows_weekday=1)
        with self.assertRaises(ValidationError) as ctx:
            info_with_weekday.full_clean()
        self.assertEqual(set(ctx.exception.message_dict), {'follows_weekday'})

        swap_out_of_range = CalendarEvent(
            kind='swap', start_date=date(2026, 10, 10), end_date=date(2026, 10, 10),
            name='x', follows_weekday=8)
        with self.assertRaises(ValidationError) as ctx:
            swap_out_of_range.full_clean()
        self.assertEqual(set(ctx.exception.message_dict), {'follows_weekday'})

        bad_kind = CalendarEvent(
            kind='party', start_date=date(2026, 10, 10), end_date=date(2026, 10, 10), name='x')
        with self.assertRaises(ValidationError) as ctx:
            bad_kind.full_clean()
        self.assertIn('kind', ctx.exception.message_dict)

        CalendarEvent(kind='swap', start_date=date(2026, 10, 10), end_date=date(2026, 10, 10),
                      name='按周一课表上课', follows_weekday=1).full_clean()
        CalendarEvent(kind='holiday', start_date=date(2026, 10, 1), end_date=date(2026, 10, 7),
                      name='国庆节放假').full_clean()

    def test_str_ordering_and_helpers(self):
        games = make_event('info', date(2026, 10, 10), date(2026, 10, 11), name='运动会')
        holiday = make_event('holiday', date(2026, 10, 1), date(2026, 10, 7), name='国庆节放假')
        exam = make_event('exam', date(2026, 10, 10), name='考试')
        self.assertEqual(list(CalendarEvent.objects.all()), [holiday, games, exam])
        self.assertEqual(str(holiday), '放假停课 2026-10-01..2026-10-07 国庆节放假')
        self.assertEqual(str(exam), '停课复习考试 2026-10-10 考试')
        self.assertTrue(holiday.suspends_classes)
        self.assertTrue(exam.suspends_classes)
        self.assertFalse(games.suspends_classes)
        self.assertTrue(holiday.covers(date(2026, 10, 7)))
        self.assertFalse(holiday.covers(date(2026, 10, 8)))

    def test_db_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_event('holiday', date(2026, 10, 7), date(2026, 10, 1))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_event('swap', date(2026, 10, 10), follows_weekday=9)
        self.assertEqual(CalendarEvent.objects.count(), 0)


class AcademicCalendarTests(TestCase):

    def setUp(self):
        self.holiday = make_event('holiday', date(2026, 10, 1), date(2026, 10, 7), name='国庆节放假')
        self.games = make_event('info', date(2026, 10, 10), date(2026, 10, 11), name='运动会')
        self.swap = make_event('swap', date(2026, 10, 10), name='按周一课表上课', follows_weekday=1)
        self.exam = make_event('exam', date(2027, 1, 11), date(2027, 1, 17), name='停课复习考试')
        self.swap_in_holiday = make_event('swap', date(2026, 10, 7), name='国庆内调休', follows_weekday=5)
        self.info_in_holiday = make_event('info', date(2026, 10, 1), name='国庆节')

    def test_events_between(self):
        with self.assertNumQueries(1):
            events = events_between(date(2026, 10, 7), date(2026, 10, 10))
        self.assertEqual(events, [self.holiday, self.swap_in_holiday, self.games, self.swap])
        self.assertEqual(events_between(date(2026, 10, 8), date(2026, 10, 9)), [])
        self.assertEqual(events_between(date(2026, 10, 10), date(2026, 10, 1)), [])
        self.assertEqual(events_between(date(2026, 10, 7), date(2026, 10, 7)),
                         [self.holiday, self.swap_in_holiday])
        self.assertEqual(events_between(date(2027, 1, 17), date(2027, 1, 18)), [self.exam])

    def test_precedence_without_further_queries(self):
        with self.assertNumQueries(1):
            calendar = calendar_between(date(2026, 9, 28), date(2026, 10, 11))
        self.assertEqual(calendar.events, [self.holiday, self.info_in_holiday,
                                           self.swap_in_holiday, self.games, self.swap])
        with self.assertNumQueries(0):
            # holiday beats info and swap; swap beats info
            self.assertEqual(calendar.kind_of(date(2026, 10, 1)), ('holiday', self.holiday))
            self.assertEqual(calendar.event_of(date(2026, 10, 7)), self.holiday)
            self.assertEqual(calendar.kind_of(date(2026, 10, 10)), ('swap', self.swap))
            self.assertEqual(calendar.kind_of(date(2026, 10, 11)), ('info', self.games))
            self.assertIsNone(calendar.kind_of(date(2026, 9, 28)))
            self.assertIsNone(calendar.event_of(date(2026, 10, 8)))
            self.assertFalse(calendar.is_class_day(date(2026, 10, 1)))
            self.assertFalse(calendar.is_class_day(date(2026, 10, 7)))
            self.assertTrue(calendar.is_class_day(date(2026, 10, 10)))
            self.assertTrue(calendar.is_class_day(date(2026, 10, 11)))
            self.assertTrue(calendar.is_class_day(date(2026, 9, 28)))
            self.assertEqual(calendar.effective_weekday(date(2026, 10, 10)), 1)
            self.assertEqual(calendar.effective_weekday(date(2026, 10, 7)), 3)   # holiday overrides the swap
            self.assertEqual(calendar.effective_weekday(date(2026, 10, 11)), 7)
            self.assertEqual(calendar.effective_weekday(date(2026, 9, 28)), 1)
            self.assertEqual(calendar.label(date(2026, 10, 1)), '国庆节放假')
            self.assertEqual(calendar.label(date(2026, 10, 10)), '按周一课表上课')
            self.assertEqual(calendar.label(date(2026, 10, 11)), '运动会')
            self.assertIsNone(calendar.label(date(2026, 9, 28)))
        self.assertTrue(calendar.covers(date(2026, 10, 1), date(2026, 10, 11)))
        self.assertTrue(calendar.covers(date(2026, 9, 28)))
        self.assertFalse(calendar.covers(date(2026, 10, 12)))
        self.assertFalse(calendar.covers(date(2026, 9, 27), date(2026, 9, 28)))
        with self.assertRaises(ValueError):
            calendar.event_of(date(2026, 10, 12))
        self.assertIn('2026-09-28..2026-10-11', repr(calendar))

    def test_exam_and_holiday_precedence(self):
        make_event('holiday', date(2027, 1, 17), name='假')
        calendar = calendar_between(date(2027, 1, 11), date(2027, 1, 18))
        self.assertEqual(calendar.kind_of(date(2027, 1, 16))[0], 'exam')
        self.assertEqual(calendar.label(date(2027, 1, 17)), '假')
        self.assertFalse(calendar.is_class_day(date(2027, 1, 17)))
        self.assertTrue(calendar.is_class_day(date(2027, 1, 18)))

    def test_same_kind_overlap_earliest_start_then_first_stored_wins(self):
        first = make_event('info', date(2026, 11, 2), date(2026, 11, 3), name='先')
        make_event('info', date(2026, 11, 2), name='后')
        earlier = make_event('info', date(2026, 11, 1), date(2026, 11, 3), name='更早')
        calendar = calendar_between(date(2026, 11, 1), date(2026, 11, 3))
        self.assertEqual([calendar.label(date(2026, 11, day)) for day in (1, 2, 3)],
                         ['更早', '更早', '更早'])
        earlier.delete()
        calendar = calendar_between(date(2026, 11, 1), date(2026, 11, 3))
        self.assertEqual([calendar.label(date(2026, 11, day)) for day in (1, 2, 3)],
                         [None, '先', '先'])
        self.assertEqual(calendar.event_of(date(2026, 11, 2)), first)

    def test_module_helpers(self):
        with self.assertNumQueries(1):
            self.assertFalse(is_class_day(date(2027, 1, 12)))
        self.assertTrue(is_class_day(date(2027, 1, 18)))
        self.assertFalse(is_class_day(date(2026, 10, 7)))
        with self.assertNumQueries(1):
            self.assertEqual(effective_weekday(date(2026, 10, 10)), 1)
        self.assertEqual(effective_weekday(date(2026, 10, 12)), 1)
        self.assertEqual(effective_weekday(date(2026, 10, 13)), 2)

    def test_edits_are_visible_to_the_next_calendar(self):
        self.assertEqual(calendar_between(date(2026, 10, 10), date(2026, 10, 10))
                         .effective_weekday(date(2026, 10, 10)), 1)
        self.swap.follows_weekday = 2
        self.swap.save()
        self.assertEqual(effective_weekday(date(2026, 10, 10)), 2)
        self.swap.delete()
        self.assertEqual(effective_weekday(date(2026, 10, 10)), 6)
        self.assertEqual(calendar_between(date(2026, 10, 10), date(2026, 10, 10))
                         .label(date(2026, 10, 10)), '运动会')
