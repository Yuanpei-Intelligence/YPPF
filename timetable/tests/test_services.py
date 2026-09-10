"""Service tests: upsert/replace semantics, expansion, conflicts, week view, agenda, ICS."""
import copy
import re
from datetime import date, datetime, time
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import Participation
from semester.models import CalendarEvent
from timetable import catalog, services
from timetable.ics import build_ics
from timetable.models import (
    AcademicTerm,
    CourseCatalogEntry,
    ImportLog,
    TimetableEntry,
    TimetableEntryOverride,
    TimetableSettings,
)
from timetable.sources.activity import ActivitySource
from timetable.sources.appoint import AppointSource
from timetable.sources.base import Occurrence
from timetable.sources.college import CollegeCourseSource
from timetable.sources.pku_parsers import LessonBlock
from timetable.sources.stored import StoredEntriesSource
from timetable.tests.helpers import (
    make_activity, make_appoint, make_college_course, make_entry,
    make_organization, make_person, make_term, portal_payload, read_fixture,
)


def _occurrence(id_, on, start, end, **extra):
    fields = {
        'id': id_, 'source': 'manual', 'kind': 'custom', 'title': id_,
        'start': datetime.combine(on, start), 'end': datetime.combine(on, end),
        'date': on, 'week': 1, 'weekday': on.isoweekday(),
    }
    fields.update(extra)
    return Occurrence(**fields)


class _LiveSource:
    """A date-based source answering with fixed occurrences (records its spans)."""

    key = 'live'
    label = '实时'

    def __init__(self, occurrences):
        self.items = list(occurrences)
        self.calls = []

    def occurrences(self, person, term, week_from, week_to, settings):
        return []

    def occurrences_between(self, person, span, settings):
        self.calls.append((span.start, span.end))
        return list(self.items)


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

    def test_import_links_catalog_and_fills_blanks_only(self):
        """README §8.1: link every block, fill blanks, never overwrite the student's values."""
        catalog.upsert_catalog_rows(self.term, [
            {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '01',
             'teacher': '束琳', 'time_text': '周一1-2节 理教406'},
            {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '02',
             'teacher': '别的老师'},
            {'course_code': '04831410', 'name': '程序设计实习', 'class_no': '01',
             'teacher': '目录教师'},
            {'course_code': '00130401', 'name': '概率统计', 'class_no': '01', 'teacher': 'A'},
            {'course_code': '00130401', 'name': '概率统计', 'class_no': '02', 'teacher': 'B'},
        ])
        rows = {(row.course_code, row.class_no): row
                for row in CourseCatalogEntry.objects.filter(term=self.term)}
        with CaptureQueriesContext(connection) as context:
            services.import_portal(self.person, self.term, portal_payload())
        catalog_queries = [q for q in context.captured_queries
                           if 'timetable_coursecatalogentry' in q['sql']]
        self.assertEqual(len(catalog_queries), 1)
        entries = TimetableEntry.objects.filter(person=self.person, term=self.term)
        math = entries.get(name='高等数学A（二）')
        # Name + teacher picked the class; blank code/class were filled, the
        # student's teacher stayed.
        self.assertEqual(math.catalog_entry, rows[('00130201', '01')])
        self.assertEqual((math.course_code, math.class_no, math.teacher),
                         ('00130201', '01', '束琳'))
        # Two classes of 概率统计 without a teacher match → not linked.
        for prob in entries.filter(name='概率统计'):
            self.assertIsNone(prob.catalog_entry)
            self.assertEqual(prob.course_code, '')
        # A different teacher spelling does not block a unique name match.
        programming = entries.get(catalog_entry=rows[('04831410', '01')])
        self.assertEqual((programming.name, programming.teacher, programming.course_code),
                         ('程序设计实习', '郭炜', '04831410'))
        # The catalog changes its teacher: a re-import keeps the student's value.
        row = rows[('00130201', '01')]
        row.teacher = '新老师'
        row.save()
        services.import_portal(self.person, self.term, portal_payload())
        math.refresh_from_db()
        self.assertEqual((math.teacher, math.catalog_entry), ('束琳', row))
        # A link the student changed survives a re-import; annotations too.
        math.catalog_entry = rows[('00130201', '02')]
        math.tag = '必修'
        math.role = TimetableEntry.Role.AUDIT
        math.category = TimetableEntry.Category.OTHER
        math.save()
        TimetableEntryOverride.objects.create(entry=math, week_start=3, week_end=3,
                                              fields={'room': '改过的教室'})
        result = services.import_portal(self.person, self.term, portal_payload())
        self.assertEqual((result.created, result.updated, result.removed), (0, 0, 0))
        math.refresh_from_db()
        self.assertEqual((math.catalog_entry, math.tag, math.role, math.category),
                         (rows[('00130201', '02')], '必修', 'audit', 'other'))
        self.assertEqual(math.overrides.get().fields, {'room': '改过的教室'})
        # Without a catalog nothing is linked and nothing breaks.
        CourseCatalogEntry.objects.all().delete()
        services.import_portal(self.other_person, self.term, portal_payload())
        self.assertFalse(TimetableEntry.objects.filter(
            person=self.other_person, catalog_entry__isnull=False).exists())

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

    def test_import_stores_exam_info_and_refreshes_it(self):
        """README §8.4: 考试信息 is an imported field, set and updated by every import."""
        services.import_portal(self.person, self.term, portal_payload())
        entries = TimetableEntry.objects.filter(person=self.person, term=self.term)
        math = entries.get(name='高等数学A（二）')
        self.assertEqual((math.exam_date, math.exam_period, math.exam_room),
                         (date(2026, 6, 18), '上午', '理教306'))
        pe = entries.get(name='体适能')
        self.assertEqual((pe.exam_date, pe.exam_period, pe.exam_room), (None, '', ''))
        math.hidden = True
        math.save()
        payload = portal_payload()
        for cell in self._math_cells(payload):
            cell['courseName'] = cell['courseName'].replace(
                '20260618 星期四 上午 理教306', '20260619 星期五 晚上 二教101')
        result = services.import_portal(self.person, self.term, payload)
        self.assertEqual((result.created, result.updated, result.removed), (0, 1, 0))
        math.refresh_from_db()
        self.assertEqual((math.exam_date, math.exam_period, math.exam_room),
                         (date(2026, 6, 19), '晚上', '二教101'))
        self.assertTrue(math.hidden)
        for cell in self._math_cells(payload):
            cell['courseName'] = cell['courseName'].split('<br>考试信息')[0] + '<br>考试信息：'
        services.import_portal(self.person, self.term, payload)
        math.refresh_from_db()
        self.assertEqual((math.exam_date, math.exam_period, math.exam_room), (None, '', ''))

    def test_upsert_normalises_exam_fields(self):
        blocks = [
            LessonBlock(name='甲', weekday=1, start_section=1, end_section=2,
                        exam_date='2027-01-12', exam_period='中午', exam_room='x' * 150),
            LessonBlock(name='乙', weekday=2, start_section=1, end_section=2,
                        exam_date='not a date', exam_period='上午', exam_room='理教101'),
        ]
        services.upsert_entries(self.person, self.term, 'paste', blocks)
        first = TimetableEntry.objects.get(person=self.person, name='甲')
        self.assertEqual((first.exam_date, first.exam_period, len(first.exam_room)),
                         (date(2027, 1, 12), '', 100))
        second = TimetableEntry.objects.get(person=self.person, name='乙')
        self.assertEqual((second.exam_date, second.exam_period, second.exam_room), (None, '', ''))

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


class ElectiveFallbackTests(TestCase):
    """README §4.4: the elective 选课结果 page stands in for an empty course table."""

    TODAY = date(2026, 9, 20)       # week 1 of the default test term (2026-09-14)

    def setUp(self):
        self.term = make_term()
        self.past = make_term(code='25-26-2', week1_monday=date(2026, 2, 23))
        self.next = make_term(code='26-27-2', week1_monday=date(2027, 2, 22))
        self.later = make_term(code='27-28-1', week1_monday=date(2027, 9, 13))
        _, self.person = make_person()
        self.calls = 0

    def results(self, html, outcome='ok'):
        def fetch():
            self.calls += 1
            return html, outcome
        return fetch

    def test_applies_to_the_covering_or_the_next_term_only(self):
        self.assertTrue(services.elective_results_apply(self.term, self.TODAY))
        self.assertTrue(services.elective_results_apply(self.next, self.TODAY))
        for term in (self.past, self.later):
            self.assertFalse(services.elective_results_apply(term, self.TODAY))
        # Between terms the next one applies, the finished one does not.
        vacation = date(2027, 2, 1)
        self.assertFalse(services.elective_results_apply(self.term, vacation))
        self.assertTrue(services.elective_results_apply(self.next, vacation))
        self.assertFalse(services.elective_results_apply(self.later, vacation))

    def test_success_without_course_list_falls_back_to_elective(self):
        # What publicQuery answered for a term without a timetable (2026-09-10).
        result = services.import_portal(
            self.person, self.term, {'success': True, 'message': '获取个人课表信息失败'},
            elective_results=self.results(read_fixture('elective_table.html')), today=self.TODAY)
        self.assertEqual(self.calls, 1)
        self.assertEqual(result.created, 4)
        self.assertEqual(result.log.message,
                         'no lessons in portal payload; imported from elective results')

    def test_empty_course_table_imports_elective_results(self):
        stale = make_entry(self.person, self.term, name='旧课')
        result = services.import_portal(
            self.person, self.term, {'success': True, 'course': []},
            elective_results=self.results(read_fixture('elective_table.html')), today=self.TODAY)
        self.assertEqual(self.calls, 1)
        self.assertEqual((result.created, result.removed), (4, 1))
        entries = TimetableEntry.objects.filter(person=self.person, term=self.term)
        self.assertEqual(set(entries.values_list('source', flat=True)), {'portal'})
        self.assertFalse(entries.filter(pk=stale.pk).exists())
        self.assertEqual(result.log.status, ImportLog.Status.OK)
        self.assertEqual(result.log.message,
                         'no lessons in portal payload; imported from elective results')
        # A later course-table import replaces the stand-in entries.
        result = services.import_portal(self.person, self.term, portal_payload(),
                                        elective_results=self.results(None), today=self.TODAY)
        self.assertEqual(self.calls, 1)
        self.assertEqual(sorted({entry.name for entry in result.entries}),
                         ['体适能', '大学英语', '概率统计', '程序设计实习', '线性代数', '高等数学A（二）'])
        self.assertEqual(result.total, 7)

    def test_not_asked_when_the_table_has_lessons_or_the_term_is_over(self):
        services.import_portal(self.person, self.term, portal_payload(),
                               elective_results=self.results(''), today=self.TODAY)
        with self.assertRaises(services.TimetableImportError):
            services.import_portal(self.person, self.past, {'success': True, 'course': []},
                                   elective_results=self.results(read_fixture('elective_table.html')),
                                   today=self.TODAY)
        self.assertEqual(self.calls, 0)
        self.assertFalse(TimetableEntry.objects.filter(term=self.past).exists())

    def test_failed_fallback_keeps_entries_and_names_the_outcome(self):
        services.import_portal(self.person, self.term, portal_payload())
        cases = [
            ({'success': True, 'course': []}, self.results(None, 'PortalUnreachable'),
             '门户未返回任何课程，本地课表未改动',
             'no lessons in portal payload; elective fallback: PortalUnreachable'),
            ({'success': False, 'remark': '未登录'}, self.results('<table class="datagrid"></table>'),
             '门户课表解析失败：未登录',
             'parse error: 未登录; elective fallback: no lessons in elective results'),
        ]
        for payload, fetch, message, log_message in cases:
            with self.subTest(log_message=log_message):
                with self.assertRaises(services.TimetableImportError) as caught:
                    services.import_portal(self.person, self.term, payload,
                                           elective_results=fetch, today=self.TODAY)
                self.assertEqual(caught.exception.message, message)
                log = ImportLog.objects.filter(person=self.person,
                                               status=ImportLog.Status.FAILED).latest('id')
                self.assertEqual(log.message, log_message)
        self.assertEqual(self.calls, 2)
        self.assertEqual(TimetableEntry.objects.filter(person=self.person).count(), 7)


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
                            source=TimetableEntry.Source.MANUAL, hidden=True,
                            category=TimetableEntry.Category.OTHER)
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
            'status', 'ref', 'hidden', 'role', 'tag', 'modified'})
        self.assertEqual((first['role'], first['tag'], first['modified']),
                         ('enrolled', '', False))
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
        self.assertTrue(settings.show_courses)
        self.assertTrue(settings.show_exams)
        self.assertEqual(settings.hidden_tags, [])

    def test_settings_payload_sources_and_tags(self):
        """README §8.3: the legend with setting names and the person's tags."""
        make_entry(self.person, self.term, name='b', weekday=3, tag='选修')
        make_entry(self.person, self.term, name='c', weekday=4, tag='必修')
        make_entry(self.person, make_term(code='25-26-2', week1_monday=date(2026, 2, 23)),
                   name='d', weekday=4, tag='旧')
        _, other = make_person('tt_other', '别人')
        make_entry(other, self.term, name='e', weekday=4, tag='别人的')
        settings = services.get_or_create_settings(self.person)
        settings.hidden_tags = ['选修', '选修', '']
        settings.show_exams = False
        settings.save()
        payload = services.settings_payload(self.person)
        self.assertEqual(payload, {
            'reminder_enabled': False, 'reminder_minutes': 20, 'show_courses': True,
            'show_college': True, 'show_activities': True, 'show_appointments': True,
            'show_exams': False, 'share_show_name': True, 'hidden_tags': ['选修'],
            'sources': [{'key': 'stored', 'label': '课程', 'setting': 'show_courses'}],
            'tags': ['必修', '旧', '选修'],
        })
        self.assertEqual(services.person_tags(other), ['别人的'])

    def test_term_payload_exam_weeks(self):
        payload = services.term_payload(self.term, date(2026, 9, 23))
        self.assertEqual((payload['exam_week_start'], payload['teaching_weeks'],
                          payload['total_weeks']), (None, 16, 16))
        self.term.total_weeks = 19
        self.term.exam_week_start = 17
        payload = services.term_payload(self.term, date(2026, 9, 23))
        self.assertEqual((payload['exam_week_start'], payload['teaching_weeks'],
                          payload['total_weeks']), (17, 16, 19))
        self.assertEqual(services.week_view(self.person, self.term, 18,
                                            today=date(2026, 9, 23))['week'], 18)


class AgendaTests(TestCase):
    """``services.agenda`` (README §6.5)."""

    DAY_KEYS = {'date', 'weekday', 'term', 'week', 'kind', 'label', 'occurrences'}

    def setUp(self):
        self.term = make_term()                      # 2026-09-14 .. 2027-01-03
        _, self.person = make_person()
        make_entry(self.person, self.term, name='高数', weekday=1)
        make_entry(self.person, self.term, name='英语', weekday=1, start_section=3, end_section=4)
        make_entry(self.person, self.term, name='周三课', weekday=3)
        make_entry(self.person, self.term, name='隐藏课', weekday=2, hidden=True)
        _, other = make_person('tt_other', '别人')
        make_entry(other, self.term, name='别人的课', weekday=1)
        self.sources = [StoredEntriesSource()]
        patcher = patch('timetable.services.load_sources', side_effect=lambda: list(self.sources))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_term_boundary(self):
        sunday = date(2026, 9, 13)
        live = _LiveSource([_occurrence('迎新', sunday, time(19, 0), time(21, 0),
                                        source='activity', kind='activity', week=0)])
        self.sources.append(live)
        view = services.agenda(self.person, sunday, 3)
        self.assertEqual(set(view), {'from', 'days', 'sources'})
        self.assertEqual(view['from'], '2026-09-13')
        self.assertEqual([day['date'] for day in view['days']],
                         ['2026-09-13', '2026-09-14', '2026-09-15'])
        before, monday, tuesday = view['days']
        self.assertEqual(set(before), self.DAY_KEYS)
        self.assertEqual((before['weekday'], before['term'], before['week'], before['kind'],
                          before['label']), (7, None, None, None, None))
        # Outside every term only the live source answers.
        self.assertEqual([o['title'] for o in before['occurrences']], ['迎新'])
        self.assertEqual((monday['term'], monday['week']), ('26-27-1', 1))
        self.assertEqual([o['title'] for o in monday['occurrences']], ['高数', '英语'])
        first = monday['occurrences'][0]
        self.assertEqual(set(first), {
            'id', 'source', 'kind', 'title', 'subtitle', 'location', 'start', 'end',
            'date', 'week', 'weekday', 'start_section', 'end_section', 'color_key',
            'status', 'ref', 'hidden', 'role', 'tag', 'modified'})
        self.assertEqual((first['start'], first['date'], first['week'], first['kind']),
                         ('2026-09-14T08:00:00', '2026-09-14', 1, 'course'))
        self.assertEqual(tuesday['occurrences'], [])            # hidden entry
        self.assertEqual(view['sources'], [{'key': 'stored', 'label': '课程'},
                                           {'key': 'live', 'label': '实时'}])
        self.assertEqual(live.calls, [(sunday, date(2026, 9, 15))])
        self.assertTrue(TimetableSettings.objects.filter(person=self.person).exists())

    def test_end_of_term_and_overlapping_terms(self):
        summer = make_term(code='26-27-3', week1_monday=date(2026, 12, 28), total_weeks=2)
        make_entry(self.person, summer, name='夏季课', weekday=1, week_end=2)
        view = services.agenda(self.person, date(2026, 12, 27), 3)
        self.assertEqual([(day['term'], day['week']) for day in view['days']],
                         [('26-27-1', 15), ('26-27-3', 1), ('26-27-3', 1)])
        # 12-28 is also fall week 16, but the summer term owns the date.
        self.assertEqual([o['title'] for o in view['days'][1]['occurrences']], ['夏季课'])
        view = services.agenda(self.person, date(2027, 1, 10), 2)
        self.assertEqual([(day['term'], day['week']) for day in view['days']],
                         [('26-27-3', 2), (None, None)])
        self.assertEqual([day['occurrences'] for day in view['days']], [[], []])

    def test_calendar_labels(self):
        CalendarEvent.objects.create(kind='holiday', start_date=date(2026, 9, 16),
                                     end_date=date(2026, 9, 16), name='中秋节放假')
        CalendarEvent.objects.create(kind='swap', start_date=date(2026, 9, 19),
                                     end_date=date(2026, 9, 19), name='按周一课表上课',
                                     follows_weekday=1)
        CalendarEvent.objects.create(kind='info', start_date=date(2026, 9, 13),
                                     end_date=date(2026, 9, 13), name='注册日')
        view = services.agenda(self.person, date(2026, 9, 13), 7)
        days = {day['date']: day for day in view['days']}
        # Labels are attached whether or not the date is in a term.
        self.assertEqual((days['2026-09-13']['term'], days['2026-09-13']['kind'],
                          days['2026-09-13']['label']), (None, 'info', '注册日'))
        self.assertEqual((days['2026-09-14']['kind'], days['2026-09-14']['label']), (None, None))
        holiday = days['2026-09-16']
        self.assertEqual((holiday['kind'], holiday['label'], holiday['occurrences']),
                         ('holiday', '中秋节放假', []))
        swap = days['2026-09-19']
        self.assertEqual((swap['kind'], swap['label']), ('swap', '按周一课表上课'))
        self.assertEqual([(o['title'], o['weekday']) for o in swap['occurrences']],
                         [('高数', 6), ('英语', 6)])

    def test_days_are_clamped_and_occurrences_sorted(self):
        monday = date(2026, 9, 14)
        live = _LiveSource([
            _occurrence('晚活动', monday, time(19, 0), time(21, 0), source='activity', kind='activity'),
            _occurrence('早活动', monday, time(7, 0), time(7, 30), source='activity', kind='activity'),
            _occurrence('隐藏活动', monday, time(12, 0), time(13, 0), hidden=True),
            _occurrence('范围外', date(2026, 10, 1), time(12, 0), time(13, 0)),
        ])
        self.sources.append(live)
        view = services.agenda(self.person, monday, 30)
        self.assertEqual(len(view['days']), services.AGENDA_MAX_DAYS)
        self.assertEqual(view['days'][-1]['date'], '2026-09-27')
        self.assertEqual([o['title'] for o in view['days'][0]['occurrences']],
                         ['早活动', '高数', '英语', '晚活动'])
        titles = [o['title'] for day in view['days'] for o in day['occurrences']]
        self.assertNotIn('隐藏活动', titles)
        self.assertNotIn('范围外', titles)
        self.assertEqual(live.calls, [(monday, date(2026, 9, 27))])
        self.assertEqual(len(services.agenda(self.person, monday, 0)['days']), 1)
        self.assertEqual(len(services.agenda(self.person, monday, 14)['days']), 14)

    def test_show_courses_hides_stored_entries(self):
        settings = services.get_or_create_settings(self.person)
        settings.show_courses = False
        settings.save(update_fields=['show_courses'])
        view = services.agenda(self.person, date(2026, 9, 14), 1)
        self.assertEqual(view['days'][0]['occurrences'], [])
        self.assertEqual(view['sources'], [{'key': 'stored', 'label': '课程'}])
        week = services.week_view(self.person, self.term, 1, today=date(2026, 9, 14))
        self.assertEqual(week['occurrences'], [])


class IcsSourceToggleTests(TestCase):
    """``build_ics`` honours the four source toggles (README §6.5)."""

    SUMMARIES = {
        'show_courses': 'SUMMARY:学校课',
        'show_college': 'SUMMARY:书院课测试',
        'show_activities': 'SUMMARY:报名活动',
        'show_appointments': 'SUMMARY:地下室 B104 研讨/活动室',
    }

    def setUp(self):
        self.term = make_term()
        self.user, self.person = make_person()
        org, teacher = make_organization()
        make_entry(self.person, self.term, name='学校课', weekday=1, week_end=1)
        make_college_course(org, self.person, datetime(2026, 9, 16, 14, 0))
        activity = make_activity(org, teacher, datetime(2026, 9, 15, 19, 0), title='报名活动')
        Participation.objects.create(activity=activity, person=self.person,
                                     status=Participation.AttendStatus.APPLYSUCCESS)
        make_appoint(self.user, datetime(2026, 9, 15, 20, 0), usage='讨论')
        patcher = patch('timetable.ics.load_sources', return_value=[
            StoredEntriesSource(), CollegeCourseSource(), ActivitySource(), AppointSource()])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = services.get_or_create_settings(self.person)

    def build(self) -> str:
        return build_ics(self.person, today=date(2026, 9, 1), now=datetime(2026, 9, 1, 12))

    def test_all_sources_by_default(self):
        text = self.build()
        for summary in self.SUMMARIES.values():
            self.assertIn(summary, text)
        self.assertEqual(text.count('BEGIN:VEVENT'), 1 + 16 + 1 + 1)
        self.assertIn('DESCRIPTION:书院老师 · 书院课', text)
        self.assertIn('CATEGORIES:预约', text)

    def test_each_toggle_removes_only_its_source(self):
        for flag, summary in self.SUMMARIES.items():
            with self.subTest(flag=flag):
                values = {name: True for name in self.SUMMARIES}
                values[flag] = False
                TimetableSettings.objects.filter(pk=self.settings.pk).update(**values)
                text = self.build()
                self.assertNotIn(summary, text)
                for other_flag, other in self.SUMMARIES.items():
                    if other_flag != flag:
                        self.assertIn(other, text)
        TimetableSettings.objects.filter(pk=self.settings.pk).update(
            **{name: False for name in self.SUMMARIES})
        self.assertEqual(self.build().count('BEGIN:VEVENT'), 0)


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
