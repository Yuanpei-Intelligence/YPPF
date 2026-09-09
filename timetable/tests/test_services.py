"""Service tests: upsert/replace semantics, expansion, conflicts, week view, ICS."""
import copy
import re
from datetime import date, datetime, time
from unittest.mock import patch

from django.test import TestCase

from timetable import services
from timetable.ics import build_ics
from timetable.models import AcademicTerm, ImportLog, TimetableEntry, TimetableSettings
from timetable.sources.base import Occurrence
from timetable.sources.pku_parsers import LessonBlock
from timetable.sources.stored import StoredEntriesSource
from timetable.tests.helpers import (
    make_entry, make_person, make_term, portal_payload, read_fixture,
)


def _occurrence(id_, on, start, end, **extra):
    fields = {
        'id': id_, 'source': 'manual', 'kind': 'custom', 'title': id_,
        'start': datetime.combine(on, start), 'end': datetime.combine(on, end),
        'date': on, 'week': 1, 'weekday': on.isoweekday(),
    }
    fields.update(extra)
    return Occurrence(**fields)


class UpsertEntriesTests(TestCase):

    def setUp(self):
        self.term = make_term()
        self.other_term = make_term(code='25-26-2', week1_monday=date(2026, 2, 23))
        _, self.person = make_person()
        _, self.other_person = make_person('tt_other', '别人')

    def _math_cells(self, payload):
        return [row['mon'] for row in payload['course'][:2]]

    def test_import_portal_creates_entries_and_log(self):
        result = services.import_portal(self.person, self.term, portal_payload())
        self.assertEqual((result.created, result.updated, result.removed), (7, 0, 0))
        self.assertEqual(result.total, 7)
        self.assertEqual(result.log.status, ImportLog.Status.OK)
        self.assertEqual(result.log.entries_count, 7)
        entries = TimetableEntry.objects.filter(person=self.person, term=self.term)
        self.assertEqual(entries.count(), 7)
        self.assertEqual(set(entries.values_list('source', flat=True)), {'portal'})
        math = entries.get(name='高等数学A（二）')
        self.assertEqual((math.weekday, math.start_section, math.end_section), (1, 1, 2))
        self.assertEqual((math.start_time, math.end_time), (time(8, 0), time(9, 50)))
        self.assertEqual(math.room, '理教406')
        self.assertEqual(math.note, '习题课')
        self.assertEqual(len(math.external_key), 40)

    def test_reimport_is_idempotent(self):
        services.import_portal(self.person, self.term, portal_payload())
        result = services.import_portal(self.person, self.term, portal_payload())
        self.assertEqual((result.created, result.updated, result.removed), (0, 0, 0))
        self.assertEqual(TimetableEntry.objects.filter(person=self.person).count(), 7)
        self.assertEqual(ImportLog.objects.filter(person=self.person).count(), 2)

    def test_reimport_updates_changed_room_and_keeps_hidden(self):
        services.import_portal(self.person, self.term, portal_payload())
        math = TimetableEntry.objects.get(person=self.person, name='高等数学A（二）')
        math.hidden = True
        math.color = '#123456'
        math.save(update_fields=['hidden', 'color'])
        payload = portal_payload()
        for cell in self._math_cells(payload):
            cell['courseName'] = cell['courseName'].replace('理教406', '理教305')
        result = services.import_portal(self.person, self.term, payload)
        self.assertEqual((result.created, result.updated, result.removed), (0, 1, 0))
        math.refresh_from_db()
        self.assertEqual(math.room, '理教305')
        self.assertTrue(math.hidden)
        self.assertEqual(math.color, '#123456')

    def test_reimport_removes_vanished_entries_only_of_that_source(self):
        services.import_portal(self.person, self.term, portal_payload())
        pasted = make_entry(self.person, self.term, name='粘贴的课',
                            source=TimetableEntry.Source.PASTE)
        manual = make_entry(self.person, self.term, name='自定义',
                            source=TimetableEntry.Source.MANUAL)
        old = make_entry(self.person, self.other_term, name='上学期')
        theirs = make_entry(self.other_person, self.term, name='别人的课')
        payload = portal_payload()
        for row in payload['course']:
            row['fri']['courseName'] = ''   # drop 概率统计 (two blocks)
        result = services.import_portal(self.person, self.term, payload)
        self.assertEqual((result.created, result.updated, result.removed), (0, 0, 2))
        self.assertEqual(result.total, 5)
        names = set(TimetableEntry.objects.filter(
            person=self.person, term=self.term).values_list('name', flat=True))
        self.assertNotIn('概率统计', names)
        for entry in (pasted, manual, old, theirs):
            self.assertTrue(TimetableEntry.objects.filter(pk=entry.pk).exists())

    def test_import_portal_failure_writes_log_and_keeps_entries(self):
        services.import_portal(self.person, self.term, portal_payload())
        with self.assertRaises(services.TimetableImportError):
            services.import_portal(self.person, self.term, {'success': False, 'remark': '未登录'})
        with self.assertRaises(services.TimetableImportError):
            services.import_portal(self.person, self.term, {'success': True, 'course': []})
        self.assertEqual(TimetableEntry.objects.filter(person=self.person).count(), 7)
        failed = ImportLog.objects.filter(person=self.person, status=ImportLog.Status.FAILED)
        self.assertEqual(failed.count(), 2)

    def test_upsert_rejects_manual_source_and_skips_unplaceable_blocks(self):
        with self.assertRaises(ValueError):
            services.upsert_entries(self.person, self.term, TimetableEntry.Source.MANUAL, [])
        blocks = [
            LessonBlock(name='好课', weekday=1, start_section=1, end_section=2),
            LessonBlock(name='坏课', weekday=9, start_section=1, end_section=2),
            LessonBlock(name='坏课2', weekday=1, start_section=0, end_section=2),
        ]
        result = services.upsert_entries(self.person, self.term, 'paste', blocks)
        self.assertEqual(result.created, 1)
        self.assertIn('skipped 2', result.log.message)

    def test_import_text_dry_run_writes_nothing(self):
        blocks = services.import_text(self.person, self.term,
                                      read_fixture('elective_table.html'), dry_run=True)
        self.assertEqual(len(blocks), 4)
        self.assertIsInstance(blocks[0], LessonBlock)
        self.assertEqual(TimetableEntry.objects.count(), 0)
        self.assertEqual(ImportLog.objects.count(), 0)

    def test_import_text_commit_and_replace(self):
        result = services.import_text(self.person, self.term, read_fixture('elective_table.html'))
        self.assertEqual((result.created, result.total), (4, 4))
        self.assertEqual(set(TimetableEntry.objects.filter(person=self.person)
                             .values_list('source', flat=True)), {'paste'})
        result = services.import_text(self.person, self.term, read_fixture('elective_plain.txt'))
        # The plain-text fixture holds the same four lessons (same keys, but
        # their raw text / teacher differ → updated) and adds 线性代数 (2).
        self.assertEqual((result.created, result.updated, result.removed), (2, 4, 0))
        self.assertEqual(result.total, 6)
        self.assertEqual(TimetableEntry.objects.filter(person=self.person).count(), 6)

    def test_import_text_unknown_format(self):
        with self.assertRaises(services.TimetableImportError) as caught:
            services.import_text(self.person, self.term, 'hello there')
        self.assertEqual(caught.exception.code, 'PARSE_FAILED')
        log = ImportLog.objects.get(person=self.person)
        self.assertEqual(log.status, ImportLog.Status.FAILED)
        self.assertEqual(log.source, TimetableEntry.Source.PASTE)


class ExpandAndConflictTests(TestCase):

    def setUp(self):
        self.term = make_term()
        _, self.person = make_person()

    def test_expand_honours_week_range_parity_and_section_times(self):
        entry = make_entry(self.person, self.term, name='奇数周课', weekday=3,
                           start_section=3, end_section=4, week_start=2, week_end=5, parity=1)
        occurrences = services.expand_entries([entry], self.term, 1, 16)
        self.assertEqual([o.week for o in occurrences], [3, 5])
        self.assertEqual([o.date for o in occurrences], [date(2026, 9, 30), date(2026, 10, 14)])
        first = occurrences[0]
        self.assertEqual(first.start, datetime(2026, 9, 30, 10, 10))
        self.assertEqual(first.end, datetime(2026, 9, 30, 12, 0))
        self.assertEqual((first.kind, first.source), ('course', 'portal'))
        self.assertEqual((first.start_section, first.end_section), (3, 4))
        self.assertEqual(first.ref, {'entry_id': entry.pk})
        self.assertEqual(first.id, f'portal:{entry.pk}:2026-09-30')
        self.assertEqual(first.weekday, 3)
        self.assertFalse(first.hidden)
        self.assertEqual(services.expand_entries([entry], self.term, 4, 4), [])
        self.assertEqual([o.week for o in services.expand_entries([entry], self.term, 5, 9)], [5])
        self.assertEqual(services.expand_entries([entry], self.term, 6, 2), [])

    def test_expand_even_parity_manual_and_hidden(self):
        even = make_entry(self.person, self.term, name='双周课', weekday=1,
                          week_start=1, week_end=16, parity=2)
        manual = make_entry(self.person, self.term, name='自习', weekday=7,
                            start_section=0, end_section=0,
                            start_time=time(21, 0), end_time=time(22, 30),
                            source=TimetableEntry.Source.MANUAL, hidden=True)
        occurrences = services.expand_entries([even, manual], self.term, 1, 4)
        even_weeks = [o.week for o in occurrences if o.title == '双周课']
        self.assertEqual(even_weeks, [2, 4])
        custom = [o for o in occurrences if o.title == '自习']
        self.assertEqual(len(custom), 4)
        self.assertEqual((custom[0].kind, custom[0].source), ('custom', 'manual'))
        self.assertIsNone(custom[0].start_section)
        self.assertEqual(custom[0].start.time(), time(21, 0))
        self.assertTrue(custom[0].hidden)
        payload = custom[0].as_dict()
        self.assertEqual(payload['start'], '2026-09-20T21:00:00')
        self.assertEqual(payload['date'], '2026-09-20')
        self.assertEqual(payload['weekday'], 7)

    def test_detect_conflicts(self):
        monday = date(2026, 9, 14)
        tuesday = date(2026, 9, 15)
        a = _occurrence('a', monday, time(8, 0), time(9, 50))
        b = _occurrence('b', monday, time(9, 0), time(10, 0))
        c = _occurrence('c', monday, time(9, 55), time(11, 0))   # chains through b
        d = _occurrence('d', monday, time(13, 0), time(14, 0))
        e = _occurrence('e', tuesday, time(8, 0), time(9, 50))   # other date
        f = _occurrence('f', monday, time(13, 30), time(15, 0), hidden=True)
        g = _occurrence('g', monday, time(14, 0), time(15, 0))   # touches d, no overlap
        groups = services.detect_conflicts([g, f, e, d, c, b, a])
        self.assertEqual(groups, [['a', 'b', 'c']])
        self.assertEqual(services.detect_conflicts([a, e]), [])
        self.assertEqual(services.detect_conflicts([]), [])


class WeekViewTests(TestCase):

    def setUp(self):
        self.term = make_term()
        _, self.person = make_person()
        self.entry = make_entry(self.person, self.term, name='高数', weekday=1)
        make_entry(self.person, self.term, name='隐藏课', weekday=2, hidden=True)
        make_entry(self.person, self.term, name='撞车课', weekday=1,
                   start_section=2, end_section=3, source=TimetableEntry.Source.PASTE)
        patcher = patch('timetable.services.load_sources',
                        return_value=[StoredEntriesSource()])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shape(self):
        view = services.week_view(self.person, self.term, 2, today=date(2026, 9, 23))
        self.assertEqual(view['week'], 2)
        self.assertEqual(view['week_dates'], [
            '2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24',
            '2026-09-25', '2026-09-26', '2026-09-27'])
        self.assertEqual(view['today'], {'date': '2026-09-23', 'weekday': 3, 'week': 2})
        self.assertEqual(view['term']['code'], '26-27-1')
        self.assertEqual(view['term']['current_week'], 2)
        self.assertEqual(view['term']['week1_monday'], '2026-09-14')
        self.assertEqual(view['term']['section_times']['1'], ['08:00', '08:50'])
        self.assertEqual(view['sources'], [{'key': 'stored', 'label': '课程'}])
        titles = [o['title'] for o in view['occurrences']]
        self.assertEqual(titles, ['高数', '撞车课'])
        self.assertNotIn('隐藏课', titles)
        first = view['occurrences'][0]
        self.assertEqual(set(first), {
            'id', 'source', 'kind', 'title', 'subtitle', 'location', 'start', 'end',
            'date', 'week', 'weekday', 'start_section', 'end_section', 'color_key',
            'status', 'ref', 'hidden'})
        self.assertEqual(first['start'], '2026-09-21T08:00:00')
        self.assertEqual(len(view['conflicts']), 1)
        self.assertEqual(set(view['conflicts'][0]), {o['id'] for o in view['occurrences']})
        self.assertTrue(TimetableSettings.objects.filter(person=self.person).exists())

    def test_week_is_clamped_and_today_outside_term(self):
        view = services.week_view(self.person, self.term, 99, today=date(2026, 9, 1))
        self.assertEqual(view['week'], 16)
        self.assertIsNone(view['today']['week'])
        self.assertIsNone(view['term']['current_week'])
        self.assertEqual(services.week_view(self.person, self.term, 0, today=date(2026, 9, 1))['week'], 1)

    def test_default_term(self):
        self.assertEqual(services.default_term(date(2026, 10, 1)), self.term)
        self.assertEqual(services.default_term(date(2026, 8, 1)), self.term)
        # A finished term stays "current" until a later one starts.
        self.assertEqual(services.default_term(date(2028, 8, 1)), self.term)
        AcademicTerm.objects.update(is_active=False)
        self.assertIsNone(services.default_term(date(2026, 10, 1)))

    def test_settings_created_with_config_default(self):
        with patch('timetable.services.CONFIG') as config:
            config.reminder_default_minutes = 35
            settings = services.get_or_create_settings(self.person)
        self.assertEqual(settings.reminder_minutes, 35)
        self.assertEqual(services.get_or_create_settings(self.person), settings)


class IcsTests(TestCase):

    def setUp(self):
        self.term = make_term()
        _, self.person = make_person()
        make_entry(self.person, self.term, name='高数, 第一部分; 加长版', weekday=1,
                   room='理教201', teacher='束琳')
        make_entry(self.person, self.term, name='单周课', weekday=3, parity=1, week_end=4)
        make_entry(self.person, self.term, name='隐藏课', weekday=4, hidden=True)
        ended = make_term(code='25-26-2', week1_monday=date(2026, 2, 23))
        make_entry(self.person, ended, name='上学期课', weekday=1)
        inactive = make_term(code='27-28-1', week1_monday=date(2027, 9, 13), is_active=False)
        make_entry(self.person, inactive, name='停用学期课', weekday=1)
        patcher = patch('timetable.ics.load_sources', return_value=[StoredEntriesSource()])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_calendar_content(self):
        text = build_ics(self.person, today=date(2026, 9, 1),
                         now=datetime(2026, 9, 1, 12, 0, 0))
        self.assertTrue(text.startswith('BEGIN:VCALENDAR\r\n'))
        self.assertTrue(text.endswith('END:VCALENDAR\r\n'))
        self.assertNotIn('\n\n', text)
        self.assertEqual(text.count('BEGIN:VEVENT'), 16 + 2)
        self.assertIn('X-WR-CALNAME:元培课表', text)
        self.assertIn('BEGIN:VTIMEZONE\r\nTZID:Asia/Shanghai', text)
        self.assertIn('DTSTART;TZID=Asia/Shanghai:20260914T080000', text)
        self.assertIn('DTEND;TZID=Asia/Shanghai:20260914T095000', text)
        self.assertIn('DTSTART;TZID=Asia/Shanghai:20260916T080000', text)     # week 1 odd
        self.assertIn('DTSTART;TZID=Asia/Shanghai:20260930T080000', text)     # week 3 odd
        self.assertNotIn('20260923T080000', text)                             # week 2 skipped
        self.assertIn('DTSTAMP:20260901T040000Z', text)
        self.assertIn('SUMMARY:高数\\, 第一部分\\; 加长版', text)
        self.assertIn('LOCATION:理教201', text)
        self.assertNotIn('隐藏课', text)
        self.assertNotIn('上学期课', text)
        self.assertNotIn('停用学期课', text)
        unfolded = text.replace('\r\n ', '')
        self.assertEqual(unfolded.count('UID:'), 18)
        for line in text.split('\r\n'):
            self.assertLessEqual(len(line.encode('utf-8')), 75, line)
            self.assertNotIn('\n', line)
        self.assertRegex(unfolded, r'UID:portal:\d+:2026-09-14@timetable\.yppf\r\n')

    def test_ended_term_included_until_its_last_week(self):
        text = build_ics(self.person, today=date(2026, 6, 1), now=datetime(2026, 6, 1))
        self.assertIn('上学期课', text)
