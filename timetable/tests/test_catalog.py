"""Course catalog tests: slot parsing, helpers, upsert/search, xlsx import command."""
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from timetable import catalog
from timetable.models import CourseCatalogEntry
from timetable.tests.helpers import make_term


def _slot(weekday, start, end, week_start=1, week_end=16, parity=0, room=''):
    return {
        'weekday': weekday, 'start_section': start, 'end_section': end,
        'week_start': week_start, 'week_end': week_end, 'parity': parity,
        'room': room,
    }


class ParseCatalogSlotsTests(SimpleTestCase):

    def test_common_forms(self):
        cases = [
            (('1-16周', '周二3-4节 理教201'), [_slot(2, 3, 4, room='理教201')]),
            (('1~16周', '周二3~4节'), [_slot(2, 3, 4)]),
            (('1-16', '星期二 第3-4节 二教107'), [_slot(2, 3, 4, room='二教107')]),
            (('1-16周', '周2 3-4'), [_slot(2, 3, 4)]),
            (('1-8周 单周', '周三5节 理教201'), [_slot(3, 5, 5, 1, 8, 1, '理教201')]),
            (('', '周四1-2节'), [_slot(4, 1, 2)]),
            (('1-16周 每周', '周二3-4节 理教201;周四5-6节 理教201'),
             [_slot(2, 3, 4, room='理教201'), _slot(4, 5, 6, room='理教201')]),
            (('1-16周', '周二3-4节 理教201；周四5-6节\n周五7-8节 二教 401'),
             [_slot(2, 3, 4, room='理教201'), _slot(4, 5, 6), _slot(5, 7, 8, room='二教 401')]),
            (('1-16周', '周二3-4节 理教201 周四5-6节 理教202'),
             [_slot(2, 3, 4, room='理教201'), _slot(4, 5, 6, room='理教202')]),
            (('1-16周', '1~16周 每周周二1~2节 理教306'), [_slot(2, 1, 2, room='理教306')]),
            (('1-16周', '1~8周 单周周三3~4节 理教306'), [_slot(3, 3, 4, 1, 8, 1, '理教306')]),
            (('1-16周', '1-8周 周二3-4节 理教201;9-16周 周四3-4节 理教201'),
             [_slot(2, 3, 4, 1, 8, 0, '理教201'), _slot(4, 3, 4, 9, 16, 0, '理教201')]),
            (('1-8周,10-16周', '周二3-4节'), [_slot(2, 3, 4, 1, 8), _slot(2, 3, 4, 10, 16)]),
            (('1-16周', '周二3-4节(单周) 理教201'), [_slot(2, 3, 4, 1, 16, 1, '理教201')]),
            (('16-1周', '周二4-3节'), [_slot(2, 3, 4)]),
            (('1-16周', '周二3-4节 理教201; 周二3-4节 理教201'), [_slot(2, 3, 4, room='理教201')]),
            (('1-16周', ''), []),
            (('1-16周', '待定'), []),
            (('1-16周', None), []),
        ]
        for (weeks_text, time_text), expected in cases:
            with self.subTest(weeks=weeks_text, time=time_text):
                self.assertEqual(catalog.parse_catalog_slots(weeks_text, time_text), expected)

    def test_default_weeks_and_out_of_range(self):
        self.assertEqual(
            catalog.parse_catalog_slots('', '周一1-2节', default_weeks=(1, 18)),
            [_slot(1, 1, 2, 1, 18)])
        self.assertEqual(catalog.parse_catalog_slots('1-16周', '周二25-26节'), [])
        self.assertEqual(catalog.parse_catalog_slots('1-40周', '周二3-4节'), [])
        self.assertEqual(set(catalog.parse_catalog_slots('1-16周', '周五7-8节')[0]),
                         set(catalog.SLOT_KEYS))


class ParseHelpersTests(SimpleTestCase):

    def test_parse_credits(self):
        cases = [
            ('2', Decimal('2.0')), (2.5, Decimal('2.5')), (3, Decimal('3.0')),
            ('3学分', Decimal('3.0')), (1.25, Decimal('1.3')), ('', None),
            ('abc', None), (None, None), (True, None), (-1, None), (1000, None),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(catalog.parse_credits(value), expected)

    def test_parse_term_code(self):
        cases = [
            ('2026-2027学年第一学期', '26-27-1'),
            ('26-27学年第1学期', '26-27-1'),
            ('2026-2027学年春季学期', '26-27-2'),
            ('2026-2027 学年 第二学期', '26-27-2'),
            ('2026-2027学年夏季学期', '26-27-3'),
            ('26-27-1', '26-27-1'),
            ('2026-2027-3', '26-27-3'),
            ('2026-2028学年第一学期', None),
            ('nonsense', None),
            ('', None),
            (None, None),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(catalog.parse_term_code(text), expected)

    def test_normalise_row(self):
        self.assertIsNone(catalog.normalise_catalog_row({'course_code': '', 'name': 'x'}))
        self.assertIsNone(catalog.normalise_catalog_row({'course_code': 'x', 'name': ' '}))
        row = catalog.normalise_catalog_row({
            'course_code': ' 00130201 ', 'name': '高等数学A（二）', 'credits': '5',
            'weeks_text': '1-16', 'time_text': '周一1-2节 理教406', 'note': 'n' * 300,
        })
        self.assertEqual(row['course_code'], '00130201')
        self.assertEqual(row['credits'], Decimal('5.0'))
        self.assertEqual(row['slots'], [_slot(1, 1, 2, room='理教406')])
        self.assertEqual(len(row['note']), 200)
        self.assertEqual(row['class_no'], '')


def _rows():
    return [
        {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '01',
         'teacher': '张三', 'credits': '5', 'weeks_text': '1-16周',
         'time_text': '周一1-2节 理教406;周三3-4节 理教406',
         'department': '数学科学学院', 'name_en': 'Advanced Mathematics A (II)'},
        {'course_code': '04831410', 'name': '程序设计实习', 'class_no': '1',
         'teacher': '李四', 'credits': 3, 'weeks_text': '1-16',
         'time_text': '周二3-4节 理教201'},
        {'course_code': '', 'name': '无课程号'},
        {'course_code': '99999999', 'name': ''},
    ]


class UpsertAndSearchTests(TestCase):

    def setUp(self):
        self.term = make_term()
        self.other_term = make_term(code='25-26-2', week1_monday=date(2026, 2, 23))

    def test_upsert_is_idempotent_and_updates_changed_rows(self):
        self.assertEqual(catalog.upsert_catalog_rows(self.term, _rows()), (2, 0))
        self.assertEqual(CourseCatalogEntry.objects.count(), 2)
        math = CourseCatalogEntry.objects.get(term=self.term, course_code='00130201')
        self.assertEqual(math.class_no, '01')
        self.assertEqual(math.credits, Decimal('5.0'))
        self.assertEqual(math.slots, [_slot(1, 1, 2, room='理教406'), _slot(3, 3, 4, room='理教406')])
        self.assertEqual(catalog.upsert_catalog_rows(self.term, _rows()), (0, 0))
        rows = _rows()
        rows[0]['teacher'] = '王五'
        self.assertEqual(catalog.upsert_catalog_rows(self.term, rows), (0, 1))
        math.refresh_from_db()
        self.assertEqual(math.teacher, '王五')
        self.assertEqual(CourseCatalogEntry.objects.count(), 2)
        self.assertEqual(catalog.upsert_catalog_rows(self.other_term, _rows()[:1]), (1, 0))
        self.assertEqual(CourseCatalogEntry.objects.filter(term=self.term).count(), 2)

    def test_duplicate_keys_in_one_batch_are_merged(self):
        rows = [
            {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '01',
             'weeks_text': '1-16周', 'time_text': '周一1-2节 理教406'},
            {'course_code': '00130201', 'name': '高等数学A（二）', 'class_no': '01',
             'teacher': '张三', 'weeks_text': '1-16周', 'time_text': '周三3-4节 理教406'},
        ]
        self.assertEqual(catalog.upsert_catalog_rows(self.term, rows), (1, 0))
        entry = CourseCatalogEntry.objects.get()
        self.assertEqual(entry.teacher, '张三')
        self.assertEqual(entry.time_text, '周一1-2节 理教406;周三3-4节 理教406')
        self.assertEqual(len(entry.slots), 2)

    def test_search(self):
        catalog.upsert_catalog_rows(self.term, _rows())
        catalog.upsert_catalog_rows(self.other_term, _rows()[:1])
        self.assertEqual([e.name for e in catalog.search_catalog(self.term, '高等')], ['高等数学A（二）'])
        self.assertEqual([e.name for e in catalog.search_catalog(self.term, '李四')], ['程序设计实习'])
        self.assertEqual([e.name for e in catalog.search_catalog(self.term, '0483')], ['程序设计实习'])
        self.assertEqual([e.name for e in catalog.search_catalog(self.term, 'advanced MATH')],
                         ['高等数学A（二）'])
        self.assertEqual(list(catalog.search_catalog(self.term, '')), [])
        self.assertEqual(list(catalog.search_catalog(self.term, '   ')), [])
        self.assertEqual(catalog.search_catalog(self.other_term, '程序').count(), 0)
        many = [{'course_code': f'{i:08d}', 'name': f'批量课程{i}', 'class_no': '01'}
                for i in range(25)]
        catalog.upsert_catalog_rows(self.term, many)
        self.assertEqual(len(list(catalog.search_catalog(self.term, '批量课程'))), 20)
        self.assertEqual(len(list(catalog.search_catalog(self.term, '批量课程', limit=5))), 5)
        self.assertEqual(len(list(catalog.search_catalog(self.term, '批量课程', limit=999))), 25)


HEADERS = ['备注', '上课时间', '起止周', '授课教师', '课程名', '课程号', '班号',
           '参考学分', '学年学期', '院系', '课程英文名', '课程类别']


class ImportCommandTests(TestCase):

    def setUp(self):
        self.term = make_term()
        self.spring = make_term(code='26-27-2', week1_monday=date(2027, 2, 22))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def workbook(self, rows, headers=HEADERS, name='catalog.xlsx', sheet='课表信息汇总',
                 preamble=()):
        workbook = Workbook()
        sheet_obj = workbook.active
        sheet_obj.title = sheet
        for line in preamble:
            sheet_obj.append(line)
        sheet_obj.append(headers)
        for row in rows:
            sheet_obj.append(row)
        workbook.create_sheet('说明').append(['无关内容'])
        path = Path(self.tmp.name) / name
        workbook.save(path)
        return str(path)

    def run_command(self, *args):
        out = StringIO()
        call_command('import_course_catalog', *args, stdout=out)
        return out.getvalue()

    def test_imports_rows_by_header_name_and_term(self):
        rows = [
            ['习题课', '周一1-2节 理教406;周三3-4节 理教406', '1-16', '张三', '高等数学A（二）',
             '00130201', '01', 5, '2026-2027学年第一学期', '数学科学学院', 'Advanced Mathematics', '必修'],
            ['', '周二3-4节 理教201', '1-16', '李四', '程序设计实习', 4831410, 1, 3.0, None,
             '信息科学技术学院', '', ''],
            ['', '周四5-6节', '1-8', '王五', '春季课', '00000001', '01', 2, '26-27-2', '', '', ''],
            ['', '周四5-6节', '1-8', '王五', '未知学期课', '00000002', '01', 2,
             '2025-2026学年第一学期', '', '', ''],
            [None] * len(HEADERS),
            ['', '', '', '', '', '00000003', '', '', '', '', '', ''],
        ]
        path = self.workbook(rows, preamble=(['课表信息汇总'], []))
        output = self.run_command(path, '--term', '26-27-1')
        self.assertIn('26-27-1: 2 row(s) -> created 2, updated 0', output)
        self.assertIn('26-27-2: 1 row(s) -> created 1, updated 0', output)
        self.assertIn('done: created 3, updated 0; skipped 1 row(s) without 课程号/课程名, '
                      '1 row(s) of unknown term(s): 25-26-1 (1)', output)
        math = CourseCatalogEntry.objects.get(course_code='00130201')
        self.assertEqual(math.term, self.term)
        self.assertEqual(math.class_no, '01')
        self.assertEqual(math.credits, Decimal('5.0'))
        self.assertEqual(math.note, '习题课')
        self.assertEqual(math.department, '数学科学学院')
        self.assertEqual(math.name_en, 'Advanced Mathematics')
        self.assertEqual(math.category, '必修')
        self.assertEqual(len(math.slots), 2)
        practice = CourseCatalogEntry.objects.get(name='程序设计实习')
        self.assertEqual(practice.course_code, '04831410')
        self.assertEqual(practice.class_no, '01')
        self.assertEqual(practice.credits, Decimal('3.0'))
        self.assertEqual(practice.slots, [_slot(2, 3, 4, room='理教201')])
        spring = CourseCatalogEntry.objects.get(name='春季课')
        self.assertEqual(spring.term, self.spring)
        self.assertFalse(CourseCatalogEntry.objects.filter(name='未知学期课').exists())
        self.assertEqual(CourseCatalogEntry.objects.count(), 3)
        output = self.run_command(path, '--term', '26-27-1')
        self.assertIn('done: created 0, updated 0', output)
        self.assertEqual(CourseCatalogEntry.objects.count(), 3)

    def test_sheet_option(self):
        path = self.workbook([['', '周二3-4节', '1-16', '李四', '课A', '00000010', '01', 2,
                               '', '', '', '']], sheet='第一张')
        self.run_command(path, '--term', '26-27-1', '--sheet', '第一张')
        self.assertEqual(CourseCatalogEntry.objects.count(), 1)
        with self.assertRaises(CommandError):
            self.run_command(path, '--term', '26-27-1', '--sheet', '不存在')

    def test_errors(self):
        path = self.workbook([])
        with self.assertRaises(CommandError):
            self.run_command(path, '--term', 'no-such')
        with self.assertRaises(CommandError):
            self.run_command(str(Path(self.tmp.name) / 'missing.xlsx'), '--term', '26-27-1')
        no_header = self.workbook([], headers=['甲', '乙'], name='noheader.xlsx')
        with self.assertRaises(CommandError):
            self.run_command(no_header, '--term', '26-27-1')
        self.assertEqual(CourseCatalogEntry.objects.count(), 0)
