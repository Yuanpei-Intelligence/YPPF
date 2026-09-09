"""
Academic calendar tests (``timetable/README.md`` §6.4): the term adapter,
calendar-aware expansion, week view days, the ICS feed, the JSON
transcription format, the ``import_academic_calendar`` command and the
shipped 2026-2027 seed files.
"""
import json
import tempfile
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

import timetable
from semester.calendar import calendar_between, is_class_day
from semester.models import CalendarEvent
from timetable import services
from timetable.calendar import (
    CalendarSpecError,
    calendar_for,
    calendars_for,
    day_info,
    parse_calendar_spec,
    replacement_window,
    week_days,
)
from timetable.ics import build_ics
from timetable.models import AcademicTerm, TimetableEntry, default_section_times
from timetable.sources.stored import StoredEntriesSource, expand_entries
from timetable.tests.helpers import make_entry, make_person, make_term

DATA_DIR = Path(timetable.__file__).resolve().parent / 'data'
# The official 2026-2027 fall calendar: week 1 starts Monday 2026-09-07,
# week 18 is 2027-01-04..01-10, 国庆 (10-01..10-07) falls in weeks 4-5.
FALL_WEEK1 = date(2026, 9, 7)


def make_event(kind, start, end=None, name='事件', follows_weekday=None, note=''):
    return CalendarEvent.objects.create(
        kind=kind, start_date=start, end_date=end or start, name=name,
        follows_weekday=follows_weekday, note=note)


def fall_events():
    make_event('holiday', date(2026, 9, 25), name='中秋节放假')
    make_event('holiday', date(2026, 10, 1), date(2026, 10, 7), name='国庆节放假')
    make_event('info', date(2026, 10, 10), date(2026, 10, 11), name='校本部秋季运动会')
    make_event('exam', date(2027, 1, 11), date(2027, 1, 17), name='停课复习考试')
    make_event('holiday', date(2027, 1, 18), date(2027, 2, 21), name='寒假')


class TermCalendarAdapterTests(TestCase):

    def setUp(self):
        self.term = make_term(week1_monday=FALL_WEEK1, total_weeks=18)
        fall_events()

    def test_calendar_for_spans_the_teaching_weeks(self):
        with self.assertNumQueries(1):
            calendar = calendar_for(self.term)
        self.assertEqual((calendar.start, calendar.end), (date(2026, 9, 7), date(2027, 1, 10)))
        # The exam period and 寒假 lie after week 18 and are not part of the term.
        self.assertEqual([event.name for event in calendar.events],
                         ['中秋节放假', '国庆节放假', '校本部秋季运动会'])
        self.assertFalse(calendar.is_class_day(date(2026, 10, 1)))
        self.assertIs(services.calendar_for, calendar_for)

    def test_calendars_for_uses_one_query(self):
        spring = make_term(code='26-27-2', week1_monday=date(2027, 2, 22), total_weeks=16)
        make_event('holiday', date(2027, 5, 1), date(2027, 5, 7), name='劳动节、校庆放假')
        with self.assertNumQueries(1):
            calendars = calendars_for([self.term, spring])
        self.assertEqual(set(calendars), {'26-27-1', '26-27-2'})
        self.assertEqual([event.name for event in calendars['26-27-1'].events],
                         ['中秋节放假', '国庆节放假', '校本部秋季运动会'])
        self.assertEqual([event.name for event in calendars['26-27-2'].events],
                         ['劳动节、校庆放假'])
        self.assertFalse(calendars['26-27-2'].is_class_day(date(2027, 5, 4)))
        self.assertEqual(calendars_for([]), {})

    def test_admin_edit_is_visible_to_the_next_call(self):
        self.assertFalse(calendar_for(self.term).is_class_day(date(2026, 9, 25)))
        event = CalendarEvent.objects.get(name='中秋节放假')
        event.start_date = date(2026, 9, 26)
        event.end_date = date(2026, 9, 27)
        event.save()
        calendar = calendar_for(self.term)
        self.assertTrue(calendar.is_class_day(date(2026, 9, 25)))
        self.assertFalse(calendar.is_class_day(date(2026, 9, 26)))
        self.assertEqual(day_info(date(2026, 9, 27))['label'], '中秋节放假')
        event.delete()
        self.assertTrue(calendar_for(self.term).is_class_day(date(2026, 9, 26)))

    def test_day_info_and_week_days(self):
        make_event('swap', date(2026, 10, 10), name='按周一课表上课', follows_weekday=1)
        calendar = calendar_for(self.term)
        with self.assertNumQueries(0):
            self.assertEqual(day_info(date(2026, 10, 1), calendar), {
                'date': '2026-10-01', 'weekday': 4, 'kind': 'holiday',
                'label': '国庆节放假', 'follows_weekday': None})
            self.assertEqual(day_info(date(2026, 10, 10), calendar), {
                'date': '2026-10-10', 'weekday': 6, 'kind': 'swap',
                'label': '按周一课表上课', 'follows_weekday': 1})
            self.assertEqual(day_info(date(2026, 10, 11), calendar), {
                'date': '2026-10-11', 'weekday': 7, 'kind': 'info',
                'label': '校本部秋季运动会', 'follows_weekday': None})
            self.assertEqual(day_info(date(2026, 9, 7), calendar), {
                'date': '2026-09-07', 'weekday': 1, 'kind': None,
                'label': None, 'follows_weekday': None})
        # A calendar that does not cover the date is replaced by a query.
        with self.assertNumQueries(1):
            info = day_info(date(2027, 1, 12), calendar)
        self.assertEqual((info['kind'], info['label']), ('exam', '停课复习考试'))
        with self.assertNumQueries(0):
            days = week_days(self.term, 4, calendar)
        self.assertEqual([day['date'] for day in days], [
            '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01',
            '2026-10-02', '2026-10-03', '2026-10-04'])
        self.assertEqual([day['kind'] for day in days],
                         [None, None, None, 'holiday', 'holiday', 'holiday', 'holiday'])
        self.assertEqual([day['weekday'] for day in days], [1, 2, 3, 4, 5, 6, 7])
        with self.assertNumQueries(1):
            self.assertEqual(week_days(self.term, 4), days)


class CalendarAwareExpansionTests(TestCase):

    def setUp(self):
        self.term = make_term(week1_monday=FALL_WEEK1, total_weeks=18)
        _, self.person = make_person()
        fall_events()
        self.monday = make_entry(self.person, self.term, name='周一课', weekday=1)
        self.odd_monday = make_entry(self.person, self.term, name='单周周一课', weekday=1,
                                     start_section=7, end_section=8, parity=1)
        self.thursday = make_entry(self.person, self.term, name='周四课', weekday=4,
                                   start_section=3, end_section=4)
        self.friday = make_entry(self.person, self.term, name='周五课', weekday=5)
        self.saturday = make_entry(self.person, self.term, name='周六课', weekday=6,
                                   start_section=5, end_section=6)
        self.entries = [self.monday, self.odd_monday, self.thursday, self.friday, self.saturday]

    @staticmethod
    def summary(occurrences):
        return [(item.title, item.date.isoformat(), item.weekday, item.week)
                for item in occurrences]

    def test_holiday_dates_produce_nothing(self):
        # 国庆 week 4 (2026-09-28..10-04): Mon-Wed classes, Thu-Sun none.
        occurrences = expand_entries(self.entries, self.term, 4, 4)
        self.assertEqual(self.summary(occurrences), [('周一课', '2026-09-28', 1, 4)])
        self.assertEqual(occurrences[0].id, f'portal:{self.monday.pk}:2026-09-28')
        # Week 3: 中秋 (Friday 09-25) skipped, odd week has the 单周 lesson.
        self.assertEqual(self.summary(expand_entries(self.entries, self.term, 3, 3)), [
            ('周一课', '2026-09-21', 1, 3),
            ('单周周一课', '2026-09-21', 1, 3),
            ('周四课', '2026-09-24', 4, 3),
            ('周六课', '2026-09-26', 6, 3),
        ])
        # Week 5 (10-05..10-11): Mon-Wed still 国庆, Thursday onwards normal.
        self.assertEqual(self.summary(expand_entries(self.entries, self.term, 5, 5)), [
            ('周四课', '2026-10-08', 4, 5),
            ('周五课', '2026-10-09', 5, 5),
            ('周六课', '2026-10-10', 6, 5),      # 运动会 is info only
        ])

    def test_swap_date_carries_the_followed_weekday(self):
        make_event('swap', date(2026, 10, 10), name='按周一课表上课', follows_weekday=1)   # Sat, week 5 (odd)
        make_event('swap', date(2026, 10, 17), name='按周一课表上课', follows_weekday=1)   # Sat, week 6 (even)
        occurrences = expand_entries(self.entries, self.term, 5, 6)
        self.assertEqual(self.summary(occurrences), [
            ('周四课', '2026-10-08', 4, 5),
            ('周五课', '2026-10-09', 5, 5),
            ('周一课', '2026-10-10', 6, 5),
            ('单周周一课', '2026-10-10', 6, 5),   # parity judged by the swap date's week
            ('周一课', '2026-10-12', 1, 6),
            ('周四课', '2026-10-15', 4, 6),
            ('周五课', '2026-10-16', 5, 6),
            ('周一课', '2026-10-17', 6, 6),      # even week: no 单周 lesson
        ])
        swapped = occurrences[2]
        self.assertEqual(swapped.id, f'portal:{self.monday.pk}:2026-10-10')
        self.assertEqual(swapped.start, datetime(2026, 10, 10, 8, 0))
        self.assertEqual(swapped.end, datetime(2026, 10, 10, 9, 50))
        self.assertEqual((swapped.start_section, swapped.end_section), (1, 2))
        self.assertEqual(swapped.ref, {'entry_id': self.monday.pk})
        self.assertEqual(len({item.id for item in occurrences}), len(occurrences))

    def test_exam_week_and_holiday_beat_swap(self):
        long_entry = make_entry(self.person, self.term, name='长课', weekday=2, week_end=20)
        self.assertEqual(self.summary(expand_entries([long_entry], self.term, 18, 20)),
                         [('长课', '2027-01-05', 2, 18)])   # 01-12 exam, 01-19 寒假
        make_event('swap', date(2026, 10, 1), name='假期内调休', follows_weekday=1)
        self.assertEqual(self.summary(expand_entries(self.entries, self.term, 4, 4)),
                         [('周一课', '2026-09-28', 1, 4)])

    def test_calendar_argument_and_queries(self):
        calendar = calendar_for(self.term)
        with self.assertNumQueries(0):
            full = expand_entries(self.entries, self.term, 1, 18, calendar)
        with self.assertNumQueries(1):
            self.assertEqual(expand_entries(self.entries, self.term, 1, 18), full)
        with self.assertNumQueries(0):
            self.assertEqual(expand_entries([], self.term, 1, 18), [])
            self.assertEqual(expand_entries(self.entries, self.term, 6, 2), [])
        # 18 Fridays minus 中秋 (09-25) and 国庆 (10-02); make_entry ends at week 16.
        fridays = [item for item in full if item.title == '周五课']
        self.assertEqual(len(fridays), 14)
        # A calendar that is too narrow is replaced by one covering the range.
        narrow = calendar_between(date(2026, 9, 7), date(2026, 9, 13))
        with self.assertNumQueries(1):
            occurrences = expand_entries([self.friday], self.term, 1, 3, narrow)
        self.assertEqual([item.date for item in occurrences],
                         [date(2026, 9, 11), date(2026, 9, 18)])
        # The stored source and the services alias go through the same code.
        source = StoredEntriesSource()
        occurrences = source.occurrences(self.person, self.term, 4, 4, None)
        self.assertEqual([item.title for item in occurrences], ['周一课'])
        self.assertIs(services.expand_entries, expand_entries)

    def test_without_events_expansion_is_unchanged(self):
        CalendarEvent.objects.all().delete()
        occurrences = expand_entries([self.friday, self.saturday], self.term, 3, 4)
        self.assertEqual([item.date.isoformat() for item in occurrences],
                         ['2026-09-25', '2026-09-26', '2026-10-02', '2026-10-03'])
        manual = make_entry(self.person, self.term, name='自习', weekday=7, hidden=True,
                            source=TimetableEntry.Source.MANUAL)
        hidden = expand_entries([manual], self.term, 1, 1)
        self.assertEqual(len(hidden), 1)
        self.assertTrue(hidden[0].hidden)
        self.assertEqual((hidden[0].kind, hidden[0].weekday), ('custom', 7))


class WeekViewCalendarTests(TestCase):

    def setUp(self):
        self.term = make_term(week1_monday=FALL_WEEK1, total_weeks=18)
        _, self.person = make_person()
        fall_events()
        make_event('swap', date(2026, 10, 10), name='按周一课表上课', follows_weekday=1)
        make_entry(self.person, self.term, name='周一课', weekday=1)
        make_entry(self.person, self.term, name='周四课', weekday=4)
        make_entry(self.person, self.term, name='周六课', weekday=6)
        patcher = patch('timetable.services.load_sources',
                        return_value=[StoredEntriesSource()])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_days_and_term_calendar(self):
        view = services.week_view(self.person, self.term, 4, today=date(2026, 10, 1))
        self.assertEqual(len(view['days']), 7)
        self.assertEqual([day['date'] for day in view['days']], view['week_dates'])
        self.assertEqual(view['days'][3], {
            'date': '2026-10-01', 'weekday': 4, 'kind': 'holiday',
            'label': '国庆节放假', 'follows_weekday': None})
        self.assertEqual(view['days'][0], {
            'date': '2026-09-28', 'weekday': 1, 'kind': None,
            'label': None, 'follows_weekday': None})
        self.assertEqual([item['title'] for item in view['occurrences']], ['周一课'])
        self.assertEqual([event['name'] for event in view['term']['calendar']],
                         ['中秋节放假', '国庆节放假', '校本部秋季运动会', '按周一课表上课'])
        self.assertEqual(view['term']['calendar'][1], {
            'kind': 'holiday', 'start': '2026-10-01', 'end': '2026-10-07',
            'name': '国庆节放假', 'follows_weekday': None})
        self.assertEqual(view['term']['calendar'][3]['follows_weekday'], 1)

    def test_swap_week(self):
        view = services.week_view(self.person, self.term, 5, today=date(2026, 10, 1))
        self.assertEqual(view['days'][5], {
            'date': '2026-10-10', 'weekday': 6, 'kind': 'swap',
            'label': '按周一课表上课', 'follows_weekday': 1})
        self.assertEqual(view['days'][6]['label'], '校本部秋季运动会')
        self.assertEqual([(item['title'], item['date']) for item in view['occurrences']],
                         [('周四课', '2026-10-08'), ('周一课', '2026-10-10')])
        self.assertEqual(view['occurrences'][1]['weekday'], 6)

    def test_term_payload_calendar(self):
        payload = services.term_payload(self.term, date(2026, 9, 7))
        self.assertEqual(len(payload['calendar']), 4)
        self.assertEqual(payload['current_week'], 1)
        calendar = calendar_for(self.term)
        with self.assertNumQueries(0):
            self.assertEqual(services.term_payload(self.term, calendar=calendar)['calendar'],
                             payload['calendar'])


class IcsCalendarTests(TestCase):

    def test_holiday_dates_have_no_vevent(self):
        term = make_term(week1_monday=FALL_WEEK1, total_weeks=18)
        _, person = make_person()
        fall_events()
        make_event('swap', date(2026, 10, 10), name='按周一课表上课', follows_weekday=1)
        make_entry(person, term, name='周一课', weekday=1, week_end=18)
        make_entry(person, term, name='周四课', weekday=4, week_end=18)
        make_entry(person, term, name='周五课', weekday=5, week_end=18)
        with patch('timetable.ics.load_sources', return_value=[StoredEntriesSource()]):
            text = build_ics(person, today=date(2026, 9, 1), now=datetime(2026, 9, 1, 12))
        self.assertNotIn('20260925T', text)     # 中秋
        self.assertNotIn('20261001T', text)     # 国庆 Thursday
        self.assertNotIn('20261002T', text)     # 国庆 Friday
        self.assertNotIn('20261005T', text)     # 国庆 Monday
        self.assertIn('DTSTART;TZID=Asia/Shanghai:20261008T080000', text)
        self.assertIn('DTSTART;TZID=Asia/Shanghai:20261010T080000', text)   # swap: Monday's class
        # Mondays 18 - 1 (10-05) + 1 (10-10); Thursdays 18 - 1; Fridays 18 - 2.
        self.assertEqual(text.count('BEGIN:VEVENT'), 18 + 17 + 16)


class CalendarSpecTests(SimpleTestCase):

    @staticmethod
    def spec(**overrides):
        data = {
            'term': '26-27-1', 'name': '2026-2027学年秋季学期',
            'week1_monday': '2026-09-07', 'total_weeks': 18,
            'events': [
                {'kind': 'holiday', 'start': '2026-10-01', 'end': '2026-10-07',
                 'name': '国庆节放假', 'note': ' 七天 '},
                {'kind': 'swap', 'start': '2026-10-10', 'end': '2026-10-10',
                 'name': '按周一课表上课', 'follows_weekday': 1},
                {'kind': 'exam', 'start': '2027-01-11', 'end': '2027-01-17', 'name': '停课复习考试'},
                {'kind': 'info', 'start': '2026-09-26', 'end': '2026-09-27',
                 'name': '公休，课程照常进行', 'follows_weekday': None},
            ],
        }
        data.update(overrides)
        return data

    def test_parse_valid(self):
        spec = parse_calendar_spec(self.spec())
        self.assertEqual((spec.code, spec.name), ('26-27-1', '2026-2027学年秋季学期'))
        self.assertEqual((spec.week1_monday, spec.total_weeks), (date(2026, 9, 7), 18))
        self.assertEqual(spec.end_date, date(2027, 1, 10))
        self.assertEqual(spec.week_of(date(2027, 1, 11)), 19)
        self.assertEqual([event.kind for event in spec.events], ['holiday', 'swap', 'exam', 'info'])
        holiday, swap, _, info = spec.events
        self.assertEqual((holiday.start, holiday.end, holiday.note),
                         (date(2026, 10, 1), date(2026, 10, 7), '七天'))
        self.assertEqual(swap.follows_weekday, 1)
        self.assertIsNone(info.follows_weekday)
        model = swap.to_model()
        self.assertEqual((model.kind, model.start_date, model.follows_weekday),
                         ('swap', date(2026, 10, 10), 1))
        self.assertEqual(parse_calendar_spec(self.spec(events=[])).events, [])
        self.assertEqual(parse_calendar_spec(self.spec(term='2026-2027-1')).code, '2026-2027-1')

    def test_problems_are_collected(self):
        data = {
            'term': 'bad', 'name': '', 'week1_monday': '2026-09-08', 'total_weeks': 0,
            'extra': 1,
            'events': [
                {'kind': 'party', 'start': '2026-10-01', 'end': '2026-09-30', 'name': 'x'},
                {'kind': 'swap', 'start': '2026-10-10', 'end': '2026-10-10', 'name': 'y'},
                {'kind': 'info', 'start': '2026-10-10', 'end': '2026-10-10', 'name': 'z',
                 'follows_weekday': 1},
                {'kind': 'holiday', 'start': '2026/10/01', 'end': '2026-10-07', 'name': 'w',
                 'foo': 1},
                'not an object',
                {'kind': 'holiday', 'start': '2026-10-01', 'end': '2026-10-07', 'name': 'dup'},
                {'kind': 'holiday', 'start': '2026-10-01', 'end': '2026-10-07', 'name': 'dup'},
                {'kind': 'holiday', 'start': '2025-10-01', 'end': '2025-10-07', 'name': 'year'},
                {'kind': 'swap', 'start': '2026-10-10', 'end': '2026-10-10', 'name': 'v',
                 'follows_weekday': 8},
                {'kind': 'exam', 'start': '2027-01-11', 'end': '2027-01-17', 'name': 'ok',
                 'note': 'n' * 201},
            ],
        }
        with self.assertRaises(CalendarSpecError) as ctx:
            parse_calendar_spec(data)
        problems = ctx.exception.problems
        joined = '\n'.join(problems)
        for expected in [
            'document: unknown key(s) extra',
            "term: 'bad' is not a term code",
            'name: must be a non-empty string',
            'week1_monday: 2026-09-08 is not a Monday',
            'total_weeks: must be an integer between 1 and 30',
            "events[1].kind: 'party' is not one of",
            'events[1]: end 2026-09-30 is before start 2026-10-01',
            'events[2].follows_weekday: a swap needs',
            'events[3].follows_weekday: only allowed for kind "swap"',
            "events[4].start: '2026/10/01' is not an ISO date",
            'events[4]: unknown key(s) foo',
            'events[5]: must be an object',
            'events[7]: duplicate of an earlier event',
            'events: year (2025-10-01..2025-10-07) lies outside the term year',
            'events[9].follows_weekday: a swap needs',
            'events[10].note: must be a string of at most 200 characters',
        ]:
            self.assertIn(expected, joined)
        self.assertEqual(len(problems), 16, joined)
        self.assertIn('unknown key(s) extra', str(ctx.exception))

    def test_document_level_problems(self):
        with self.assertRaises(CalendarSpecError) as ctx:
            parse_calendar_spec([])
        self.assertEqual(ctx.exception.problems, ['the document must be a JSON object'])
        with self.assertRaises(CalendarSpecError) as ctx:
            parse_calendar_spec({'term': '26-27-1', 'events': {}})
        self.assertEqual(ctx.exception.problems, [
            'document: missing key(s) name, total_weeks, week1_monday',
            'name: must be a non-empty string',
            "week1_monday: None is not an ISO date (YYYY-MM-DD)",
            'total_weeks: must be an integer between 1 and 30',
            'events: must be a list',
        ])
        with self.assertRaises(CalendarSpecError):
            parse_calendar_spec(self.spec(total_weeks=True))
        with self.assertRaises(CalendarSpecError):
            parse_calendar_spec(self.spec(name='x' * 33))

    def test_replacement_window(self):
        spec = parse_calendar_spec(self.spec())
        self.assertEqual(replacement_window(spec), (date(2026, 9, 7), date(2027, 1, 17)))
        self.assertEqual(replacement_window(parse_calendar_spec(self.spec(events=[]))),
                         (date(2026, 9, 7), date(2027, 1, 10)))
        early = self.spec(events=[{'kind': 'info', 'start': '2026-09-05', 'end': '2026-09-06',
                                   'name': '新生注册'}])
        self.assertEqual(replacement_window(parse_calendar_spec(early)),
                         (date(2026, 9, 5), date(2027, 1, 10)))


class ImportCommandTests(TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fall = json.loads((DATA_DIR / 'calendar_26-27-1.json').read_text(encoding='utf-8'))

    def write(self, data, name='calendar.json') -> str:
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return str(path)

    def run_command(self, *args) -> str:
        out = StringIO()
        call_command('import_academic_calendar', *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def rows():
        return sorted(CalendarEvent.objects.values_list(
            'kind', 'start_date', 'end_date', 'name', 'follows_weekday', 'note'))

    def test_creates_term_and_events(self):
        output = self.run_command(self.write(self.fall))
        self.assertIn('26-27-1 2026-2027学年秋季学期: week 1 from 2026-09-07, 18 week(s) (new term)',
                      output)
        self.assertIn('holiday  2026-10-01 .. 2026-10-07  weeks 4-5    国庆节放假', output)
        self.assertIn('exam     2027-01-11 .. 2027-01-17  week 19      停课复习考试', output)
        self.assertIn('holiday  2027-01-18 .. 2027-02-21  weeks 20-24  寒假', output)
        self.assertIn('done: created term 26-27-1, replaced 0 event(s) in '
                      '2026-09-07 .. 2027-02-21 with 8', output)
        term = AcademicTerm.objects.get(code='26-27-1')
        self.assertEqual((term.name, term.week1_monday, term.total_weeks, term.is_active),
                         ('2026-2027学年秋季学期', date(2026, 9, 7), 18, True))
        self.assertEqual(term.section_times, default_section_times())
        self.assertEqual(CalendarEvent.objects.count(), 8)
        holiday = CalendarEvent.objects.get(name='国庆节放假')
        self.assertEqual((holiday.kind, holiday.start_date, holiday.end_date, holiday.follows_weekday),
                         ('holiday', date(2026, 10, 1), date(2026, 10, 7), None))

    def test_idempotent_and_keeps_local_term_fields(self):
        term = make_term(week1_monday=date(2026, 9, 14), total_weeks=16, name='旧名')
        term.section_times = {'1': ['08:30', '09:20']}
        term.is_active = False
        term.save()
        make_event('info', date(2026, 9, 20), name='旧事件')                       # inside the window
        make_event('holiday', date(2027, 5, 1), date(2027, 5, 7), name='劳动节')   # after it
        make_event('info', date(2026, 7, 1), name='暑期')                          # before it
        path = self.write(self.fall)
        output = self.run_command(path)
        self.assertIn('(existing term, name 旧名 -> 2026-2027学年秋季学期, '
                      'week1_monday 2026-09-14 -> 2026-09-07, total_weeks 16 -> 18)', output)
        self.assertIn('done: updated term 26-27-1, replaced 1 event(s)', output)
        term.refresh_from_db()
        self.assertEqual((term.name, term.week1_monday, term.total_weeks),
                         ('2026-2027学年秋季学期', date(2026, 9, 7), 18))
        self.assertEqual(term.section_times, {'1': ['08:30', '09:20']})
        self.assertFalse(term.is_active)
        self.assertFalse(CalendarEvent.objects.filter(name='旧事件').exists())
        self.assertTrue(CalendarEvent.objects.filter(name='劳动节').exists())
        self.assertTrue(CalendarEvent.objects.filter(name='暑期').exists())
        first = self.rows()
        self.assertEqual(len(first), 10)
        output = self.run_command(path)
        self.assertIn('(existing term, unchanged)', output)
        self.assertIn('done: kept term 26-27-1, replaced 8 event(s) in '
                      '2026-09-07 .. 2027-02-21 with 8', output)
        self.assertEqual(self.rows(), first)
        self.assertEqual(AcademicTerm.objects.count(), 1)

    def test_dry_run_writes_nothing(self):
        path = self.write(self.fall)
        output = self.run_command(path, '--dry-run')
        self.assertIn('(new term)', output)
        self.assertIn('dry run: would replace 0 event(s) in 2026-09-07 .. 2027-02-21 with 8; '
                      'nothing written', output)
        self.assertFalse(AcademicTerm.objects.filter(code='26-27-1').exists())
        self.assertEqual(CalendarEvent.objects.count(), 0)
        make_term(week1_monday=date(2026, 9, 14))
        make_event('info', date(2026, 9, 20), name='旧事件')
        output = self.run_command(path, '--dry-run')
        self.assertIn('week1_monday 2026-09-14 -> 2026-09-07', output)
        self.assertIn('would replace 1 event(s)', output)
        self.assertEqual(AcademicTerm.objects.get(code='26-27-1').week1_monday, date(2026, 9, 14))
        self.assertTrue(CalendarEvent.objects.filter(name='旧事件').exists())

    def test_invalid_input_writes_nothing(self):
        bad = dict(self.fall)
        bad['events'] = list(self.fall['events']) + [
            {'kind': 'swap', 'start': '2026-10-10', 'end': '2026-10-10', 'name': '缺星期'}]
        with self.assertRaises(CommandError) as ctx:
            self.run_command(self.write(bad))
        self.assertIn('events[9].follows_weekday', str(ctx.exception))
        with self.assertRaises(CommandError) as ctx:
            self.run_command(self.write({'term': '26-27-1'}, 'partial.json'))
        self.assertIn('missing key(s)', str(ctx.exception))
        with self.assertRaises(CommandError) as ctx:
            self.run_command(str(Path(self.tmp.name) / 'missing.json'))
        self.assertIn('cannot read', str(ctx.exception))
        broken = Path(self.tmp.name) / 'broken.json'
        broken.write_text('{not json', encoding='utf-8')
        with self.assertRaises(CommandError) as ctx:
            self.run_command(str(broken))
        self.assertIn('not valid JSON', str(ctx.exception))
        self.assertFalse(AcademicTerm.objects.exists())
        self.assertEqual(CalendarEvent.objects.count(), 0)

    def test_seed_files_load_cleanly(self):
        for name in ('calendar_26-27-1.json', 'calendar_26-27-2.json'):
            output = self.run_command(str(DATA_DIR / name))
            self.assertIn('done: created term', output)
        fall = AcademicTerm.objects.get(code='26-27-1')
        spring = AcademicTerm.objects.get(code='26-27-2')
        self.assertEqual((fall.name, fall.week1_monday, fall.total_weeks),
                         ('2026-2027学年秋季学期', date(2026, 9, 7), 18))
        self.assertEqual((spring.name, spring.week1_monday, spring.total_weeks),
                         ('2026-2027学年春季学期', date(2027, 2, 22), 16))
        self.assertEqual(fall.end_date(), date(2027, 1, 10))
        self.assertEqual(spring.end_date(), date(2027, 6, 13))
        self.assertEqual(CalendarEvent.objects.count(), 12)
        by_name = {event.name: event for event in CalendarEvent.objects.all()}
        self.assertEqual((by_name['中秋节放假'].start_date, by_name['中秋节放假'].end_date),
                         (date(2026, 9, 25), date(2026, 9, 25)))
        self.assertEqual((by_name['国庆节放假'].start_date, by_name['国庆节放假'].end_date),
                         (date(2026, 10, 1), date(2026, 10, 7)))
        self.assertEqual((by_name['校本部秋季运动会'].kind, by_name['校本部秋季运动会'].start_date,
                          by_name['校本部秋季运动会'].end_date),
                         ('info', date(2026, 10, 10), date(2026, 10, 11)))
        self.assertEqual((by_name['寒假'].start_date, by_name['寒假'].end_date),
                         (date(2027, 1, 18), date(2027, 2, 21)))
        self.assertEqual((by_name['劳动节、校庆放假'].start_date, by_name['劳动节、校庆放假'].end_date),
                         (date(2027, 5, 1), date(2027, 5, 7)))
        self.assertIn('校庆', by_name['劳动节、校庆放假'].note)
        self.assertEqual(by_name['暑假'].start_date, date(2027, 6, 28))
        exams = CalendarEvent.objects.filter(kind='exam').order_by('start_date')
        self.assertEqual([(e.start_date, e.end_date) for e in exams], [
            (date(2027, 1, 11), date(2027, 1, 17)), (date(2027, 6, 14), date(2027, 6, 27))])
        self.assertFalse(CalendarEvent.objects.filter(kind='swap').exists())
        # The fall window ends the day before spring week 1, so re-importing
        # one file leaves the other term's rows alone.
        self.run_command(str(DATA_DIR / 'calendar_26-27-1.json'))
        self.assertEqual(CalendarEvent.objects.count(), 12)
        # Calendar semantics of a few well-known dates.
        calendar = calendar_for(fall)
        self.assertFalse(calendar.is_class_day(date(2026, 9, 25)))
        self.assertFalse(calendar.is_class_day(date(2026, 10, 1)))
        self.assertTrue(calendar.is_class_day(date(2026, 9, 30)))
        self.assertEqual(calendar.label(date(2026, 9, 30)), '公休，课程照常进行')
        self.assertEqual(calendar.label(date(2026, 10, 10)), '公休，课程照常进行')
        self.assertEqual(calendar.label(date(2026, 10, 11)), '校本部秋季运动会')
        self.assertEqual(calendar.effective_weekday(date(2026, 10, 10)), 6)
        self.assertTrue(is_class_day(date(2027, 1, 8)))
        self.assertFalse(is_class_day(date(2027, 1, 12)))
        self.assertFalse(is_class_day(date(2027, 2, 1)))
        self.assertTrue(is_class_day(date(2027, 2, 22)))
        self.assertFalse(is_class_day(date(2027, 5, 4)))
        self.assertTrue(is_class_day(date(2027, 5, 8)))
        self.assertFalse(is_class_day(date(2027, 6, 20)))
        self.assertFalse(is_class_day(date(2027, 7, 1)))
