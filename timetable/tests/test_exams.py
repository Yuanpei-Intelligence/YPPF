"""Exam schedule tests (``timetable/README.md`` §8.4): parser, source, command."""
import csv
import tempfile
from datetime import date, datetime, time
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from timetable import catalog
from timetable.exams import (
    ExamIndex, entry_exam_window, exams_for_entries, match_exams, parse_exam_time,
)
from timetable.models import AcademicTerm, CourseExam, TimetableEntry, TimetableSettings
from timetable.sources import base
from timetable.sources.exam import ExamSource
from timetable.tests.helpers import make_entry, make_person, make_term

# A synthetic 19-week term starting 2026-09-07 (week 19 = 2027-01-11..17); the
# real 2026-2027 fall term has 18 weeks (calendar_26-27-1.json).
FALL = AcademicTerm(code='26-27-1', name='fall', week1_monday=date(2026, 9, 7),
                    total_weeks=19, exam_week_start=17)


class ParseExamTimeTests(SimpleTestCase):

    def test_supported_formats(self):
        start = datetime(2027, 1, 11, 8, 30)
        end = datetime(2027, 1, 11, 10, 30)
        cases = [
            '2027-01-11 08:30-10:30',
            '2027/1/11 8:30～10:30',
            '2027.1.11 8：30—10：30',
            '2027年1月11日 08:30-10:30',
            '2027年1月11日08:30至10:30',
            '1月11日（周一）8:30-10:30',
            '1月11日 周一 8:30-10:30',
            '第19周 周一 08:30-10:30',
            '第19周星期一08:30-10:30',
            '19周 周1 8点30分-10点30分',
            '2027-01-11（周一）上午08:30-10:30',
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_exam_time(text, FALL), (start, end))

    def test_year_from_the_term_span(self):
        self.assertEqual(parse_exam_time('9月20日 10:00-12:00', FALL),
                         (datetime(2026, 9, 20, 10, 0), datetime(2026, 9, 20, 12, 0)))
        spring = AcademicTerm(code='26-27-2', name='s', week1_monday=date(2027, 2, 22),
                              total_weeks=18, exam_week_start=17)
        self.assertEqual(parse_exam_time('6月15日 14:00-16:00', spring),
                         (datetime(2027, 6, 15, 14, 0), datetime(2027, 6, 15, 16, 0)))
        self.assertEqual(parse_exam_time('第17周 周二 14:00-16:00', spring),
                         (datetime(2027, 6, 15, 14, 0), datetime(2027, 6, 15, 16, 0)))

    def test_separate_cells_and_workbook_values(self):
        expected = (datetime(2027, 1, 11, 8, 30), datetime(2027, 1, 11, 10, 30))
        self.assertEqual(parse_exam_time('2027-01-11', FALL, start_text='08:30',
                                         end_text='10:30'), expected)
        self.assertEqual(parse_exam_time(date(2027, 1, 11), FALL, start_text=time(8, 30),
                                         end_text=time(10, 30)), expected)
        self.assertEqual(parse_exam_time(datetime(2027, 1, 11, 0, 0), FALL,
                                         start_text='8:30', end_text='10:30'), expected)
        self.assertEqual(parse_exam_time(datetime(2027, 1, 11, 8, 30), FALL),
                         (datetime(2027, 1, 11, 8, 30), datetime(2027, 1, 11, 10, 30)))
        # The start cell may carry the whole datetime.
        self.assertEqual(parse_exam_time('', FALL, start_text='2027-01-11 08:30',
                                         end_text='2027-01-11 10:30'), expected)

    def test_defaults_and_afternoon(self):
        self.assertEqual(parse_exam_time('2027-01-11 08:30', FALL),
                         (datetime(2027, 1, 11, 8, 30), datetime(2027, 1, 11, 10, 30)))
        self.assertEqual(parse_exam_time('第3周 星期五 14:00', FALL),
                         (datetime(2026, 9, 25, 14, 0), datetime(2026, 9, 25, 16, 0)))
        self.assertEqual(parse_exam_time('2027-01-11 下午2:30-4:30', FALL),
                         (datetime(2027, 1, 11, 14, 30), datetime(2027, 1, 11, 16, 30)))
        self.assertEqual(parse_exam_time('2027-01-11 晚上7:00-9:00', FALL),
                         (datetime(2027, 1, 11, 19, 0), datetime(2027, 1, 11, 21, 0)))
        # An end that does not follow the start is replaced by the default.
        self.assertEqual(parse_exam_time('2027-01-11 10:30-08:30', FALL),
                         (datetime(2027, 1, 11, 10, 30), datetime(2027, 1, 11, 12, 30)))

    def test_unreadable(self):
        for text in ('', None, '待定', '08:30-10:30', '2027-13-40 08:30', '第0周 周一 08:30',
                     '第19周 08:30-10:30', '2027-01-11', '2027-01-11 25:70'):
            with self.subTest(text=text):
                self.assertIsNone(parse_exam_time(text, FALL))


class ExamSourceTests(TestCase):

    def setUp(self):
        self.term = make_term(week1_monday=date(2026, 9, 7), total_weeks=19)
        self.term.exam_week_start = 17
        self.term.save()
        _, self.person = make_person()
        self.settings = TimetableSettings.objects.create(person=self.person)
        self.source = ExamSource()

        def exam(code, class_no, name, start, **extra):
            fields = {'end': start.replace(hour=start.hour + 2), 'room': '考场'}
            fields.update(extra)
            return CourseExam.objects.create(
                term=self.term, course_code=code, class_no=class_no, name=name,
                start=start, **fields)

        self.math_exam = exam('00130201', '01', '高等数学A（二）', datetime(2027, 1, 12, 8, 30),
                              method='闭卷', room='理教201', teacher='张三')
        exam('00130201', '02', '高等数学A（二）', datetime(2027, 1, 12, 10, 30))
        self.prog_exam = exam('04831410', '01', '程序设计实习', datetime(2027, 1, 13, 14, 0),
                              teacher='李四')
        self.linear_exam = exam('00130301', '01', '线性代数', datetime(2027, 1, 14, 8, 30))
        exam('00130401', '01', '概率统计', datetime(2027, 1, 15, 8, 30))
        exam('00130401', '02', '概率统计', datetime(2027, 1, 15, 10, 30))
        exam('00130501', '03', '大学英语', datetime(2027, 1, 16, 8, 30))
        exam('00130601', '01', '数据结构', datetime(2027, 1, 16, 14, 0))
        self.midterm = exam('00130201', '01', '高等数学A（二）', datetime(2026, 11, 4, 19, 0),
                            note='期中')

        self.math1 = make_entry(self.person, self.term, name='高等数学A（二）', weekday=1,
                                course_code='00130201', class_no='01', week_end=16)
        self.math2 = make_entry(self.person, self.term, name='高等数学A（二）', weekday=3,
                                course_code='00130201', class_no='01', week_end=16)
        self.prog = make_entry(self.person, self.term, name='程序设计实习', weekday=2,
                               course_code='4831410', week_end=16)
        self.linear = make_entry(self.person, self.term, name='线性代数', weekday=4, week_end=16)
        self.prob = make_entry(self.person, self.term, name='概率统计', weekday=5,
                               course_code='00130401', week_end=16)
        make_entry(self.person, self.term, name='数据结构', weekday=5, start_section=3,
                   end_section=4, course_code='00130601', class_no='01', hidden=True,
                   week_end=16)
        make_entry(self.person, self.term, name='自习', weekday=6, week_end=16,
                   source=TimetableEntry.Source.MANUAL,
                   category=TimetableEntry.Category.OTHER)
        catalog.upsert_catalog_rows(self.term, [
            {'course_code': '00130501', 'name': '大学英语', 'class_no': '03', 'teacher': '王五'}])
        self.english = make_entry(self.person, self.term, name='英语（旁听）', weekday=6,
                                  start_section=3, end_section=4, week_end=16,
                                  source=TimetableEntry.Source.MANUAL,
                                  catalog_entry=catalog.match_catalog(
                                      self.term, course_code='00130501', class_no='03'))
        _, other = make_person('tt_other', '别人')
        make_entry(other, self.term, name='概率统计', weekday=1, course_code='00130401',
                   class_no='02', week_end=16)

    def occurrences(self, week_from=1, week_to=19, settings=None):
        return self.source.occurrences(self.person, self.term, week_from, week_to,
                                       settings or self.settings)

    def test_matching_rules_and_dedupe(self):
        occurrences = self.occurrences()
        self.assertEqual([(o.title, o.ref['entry_id']) for o in occurrences], [
            ('高等数学A（二） 考试', self.math1.pk),        # midterm, week 9
            ('高等数学A（二） 考试', self.math1.pk),        # code+class; second slot deduped
            ('程序设计实习 考试', self.prog.pk),            # code only, zero-padded, one class
            ('线性代数 考试', self.linear.pk),              # exact name
            ('大学英语 考试', self.english.pk),             # catalog values when linked
        ])
        # 概率统计 has two classes and no class number on the entry → ambiguous.
        self.assertNotIn('概率统计 考试', [o.title for o in occurrences])
        first = occurrences[1]
        self.assertEqual(first.id, f'exam:{self.math_exam.pk}:2027-01-12')
        self.assertEqual((first.source, first.kind), ('exam', 'exam'))
        self.assertEqual((first.subtitle, first.location), ('闭卷', '理教201'))
        self.assertEqual((first.start, first.end),
                         (datetime(2027, 1, 12, 8, 30), datetime(2027, 1, 12, 10, 30)))
        self.assertEqual((first.date, first.week, first.weekday), (date(2027, 1, 12), 19, 2))
        self.assertEqual((first.start_section, first.end_section), (None, None))
        self.assertEqual(first.color_key, '高等数学A（二）')
        self.assertEqual(first.ref, {'exam_id': self.math_exam.pk, 'entry_id': self.math1.pk})
        self.assertEqual((first.role, first.status, first.hidden), ('', '', False))
        # Subtitle falls back to the teacher.
        self.assertEqual(occurrences[2].subtitle, '李四')
        self.assertEqual((self.source.key, self.source.label, self.source.setting),
                         ('exam', '考试', 'show_exams'))

    def test_week_range_settings_and_hidden_tags(self):
        self.assertEqual([o.title for o in self.occurrences(9, 9)], ['高等数学A（二） 考试'])
        self.assertEqual(self.occurrences(1, 8), [])
        self.assertEqual(len(self.occurrences(19, 19)), 4)
        self.assertEqual(self.occurrences(5, 2), [])
        self.settings.show_exams = False
        self.assertEqual(self.occurrences(), [])
        self.settings.show_exams = True
        self.math1.tag = '隐藏我'
        self.math1.save()
        self.math2.tag = '隐藏我'
        self.math2.save()
        self.settings.hidden_tags = ['隐藏我']
        self.assertNotIn('高等数学A（二） 考试', [o.title for o in self.occurrences()])
        self.assertEqual(len(self.source.occurrences(self.person, self.term, 1, 19, None)), 5)

    def test_occurrences_between_and_entry_lookup(self):
        span = base.DateSpan.load(date(2027, 1, 12), date(2027, 1, 13))
        occurrences = base.occurrences_between(self.source, self.person, span, self.settings)
        self.assertEqual([(o.title, o.date) for o in occurrences],
                         [('高等数学A（二） 考试', date(2027, 1, 12)),
                          ('程序设计实习 考试', date(2027, 1, 13))])
        with self.assertNumQueries(1):
            by_entry = exams_for_entries(self.term, [self.math1, self.prob, self.linear])
        self.assertEqual([e.pk for e in by_entry[self.math1.pk]],
                         [self.midterm.pk, self.math_exam.pk])
        self.assertEqual(by_entry[self.prob.pk], [])
        self.assertEqual([e.pk for e in by_entry[self.linear.pk]], [self.linear_exam.pk])
        self.assertEqual(exams_for_entries(self.term, []), {})
        pairs = match_exams([self.math2, self.math1], CourseExam.objects.filter(term=self.term))
        self.assertEqual([(exam.pk, entry.pk) for exam, entry in pairs],
                         [(self.midterm.pk, self.math2.pk), (self.math_exam.pk, self.math2.pk)])
        index = ExamIndex([])
        self.assertEqual(index.match_entry(self.math1), [])


class OwnExamTests(TestCase):
    """The course table's own 考试信息 when no ``CourseExam`` covers the course (§8.4)."""

    def setUp(self):
        self.term = make_term(week1_monday=date(2026, 9, 7), total_weeks=19)
        _, self.person = make_person()
        self.settings = TimetableSettings.objects.create(person=self.person)
        self.source = ExamSource()
        own = {'exam_date': date(2027, 1, 12), 'exam_period': '上午', 'exam_room': '二教411'}
        self.quantum1 = make_entry(self.person, self.term, name='量子力学', weekday=2, **own)
        self.quantum2 = make_entry(self.person, self.term, name='量子力学', weekday=4, **own)
        # In the exam schedule on another date: the schedule wins, no duplicate.
        self.math = make_entry(self.person, self.term, name='高等数学A（二）', weekday=1,
                               course_code='00130201', class_no='01',
                               exam_date=date(2027, 1, 13), exam_period='下午',
                               exam_room='理教101')
        self.math_exam = CourseExam.objects.create(
            term=self.term, course_code='00130201', class_no='01', name='高等数学A（二）',
            start=datetime(2027, 1, 14, 8, 30), end=datetime(2027, 1, 14, 10, 30),
            room='理教201')
        self.solid = make_entry(self.person, self.term, name='固体物理学', weekday=5,
                                exam_date=date(2027, 1, 17), exam_period='晚上')
        make_entry(self.person, self.term, name='隐藏的课', weekday=3, hidden=True,
                   exam_date=date(2027, 1, 12), exam_period='下午')
        _, other = make_person('tt_other', '别人')
        make_entry(other, self.term, name='别人的课', exam_date=date(2027, 1, 12),
                   exam_period='上午')

    def occurrences(self, week_from=1, week_to=19):
        return self.source.occurrences(self.person, self.term, week_from, week_to,
                                       self.settings)

    def test_own_exam_once_per_course_and_date(self):
        occurrences = self.occurrences()
        self.assertEqual([(o.id, o.title) for o in occurrences], [
            (f'exam:entry{self.quantum1.pk}:2027-01-12', '量子力学 考试'),
            (f'exam:{self.math_exam.pk}:2027-01-14', '高等数学A（二） 考试'),
            (f'exam:entry{self.solid.pk}:2027-01-17', '固体物理学 考试'),
        ])
        quantum = occurrences[0]
        self.assertEqual((quantum.source, quantum.kind, quantum.subtitle, quantum.location),
                         ('exam', 'exam', '教务部统一考试时段', '二教411'))
        self.assertEqual((quantum.start, quantum.end),
                         (datetime(2027, 1, 12, 8, 30), datetime(2027, 1, 12, 10, 30)))
        self.assertEqual((quantum.date, quantum.week, quantum.weekday), (date(2027, 1, 12), 19, 2))
        self.assertEqual((quantum.start_section, quantum.end_section, quantum.color_key),
                         (None, None, '量子力学'))
        self.assertEqual((quantum.ref, quantum.role, quantum.status, quantum.hidden),
                         ({'entry_id': self.quantum1.pk}, '', '', False))
        solid = occurrences[2]
        self.assertEqual((solid.start, solid.end, solid.location),
                         (datetime(2027, 1, 17, 18, 30), datetime(2027, 1, 17, 20, 30), ''))
        # Another date of the same course is another exam.
        make_entry(self.person, self.term, name='量子力学', weekday=5, start_section=3,
                   end_section=4, exam_date=date(2027, 1, 15), exam_period='下午')
        dated = [(o.title, o.date) for o in self.occurrences(19, 19)]
        self.assertEqual(dated.count(('量子力学 考试', date(2027, 1, 12))), 1)
        self.assertIn(('量子力学 考试', date(2027, 1, 15)), dated)

    def test_span_settings_and_hidden_tags(self):
        self.assertEqual(self.occurrences(1, 18), [])
        self.assertEqual([o.title for o in self.occurrences(19, 19)],
                         ['量子力学 考试', '高等数学A（二） 考试', '固体物理学 考试'])
        self.settings.show_exams = False
        self.assertEqual(self.occurrences(), [])
        self.settings.show_exams = True
        for entry in (self.quantum1, self.quantum2):
            entry.tag = '不看'
            entry.save()
        self.settings.hidden_tags = ['不看']
        self.assertEqual([o.title for o in self.occurrences()],
                         ['高等数学A（二） 考试', '固体物理学 考试'])

    def test_date_span_and_window_helper(self):
        span = base.DateSpan.load(date(2027, 1, 12), date(2027, 1, 12))
        self.assertEqual(
            [o.id for o in base.occurrences_between(self.source, self.person, span, self.settings)],
            [f'exam:entry{self.quantum1.pk}:2027-01-12'])
        self.assertEqual(entry_exam_window(self.math),
                         (datetime(2027, 1, 13, 14, 0), datetime(2027, 1, 13, 16, 0)))
        self.solid.exam_period = ''
        self.assertEqual(entry_exam_window(self.solid),
                         (datetime(2027, 1, 17, 8, 30), datetime(2027, 1, 17, 10, 30)))
        self.assertIsNone(entry_exam_window(make_entry(self.person, self.term, name='无考试')))


HEADERS = ['课程号', '课程名', '班号', '教师', '考试时间', '考试地点', '考试方式', '备注']


class ImportExamScheduleCommandTests(TestCase):

    def setUp(self):
        self.term = make_term(week1_monday=date(2026, 9, 7), total_weeks=19)
        self.term.exam_week_start = 17
        self.term.save()
        make_term(code='26-27-2', week1_monday=date(2027, 2, 22))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def workbook(self, rows, headers=HEADERS, preamble=(), name='exams.xlsx'):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '考试安排'
        for line in preamble:
            sheet.append(line)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        workbook.create_sheet('说明').append(['无关内容'])
        path = Path(self.tmp.name) / name
        workbook.save(path)
        return str(path)

    def csv_file(self, rows, headers, name='exams.csv'):
        path = Path(self.tmp.name) / name
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        return str(path)

    def run_command(self, *args):
        out = StringIO()
        call_command('import_exam_schedule', *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def rows():
        return list(CourseExam.objects.order_by('start', 'course_code').values_list(
            'course_code', 'class_no', 'name', 'start', 'end', 'room', 'method'))

    def test_xlsx_upsert_and_skips(self):
        path = self.workbook([
            ['00130201', '高等数学A（二）', '01', '张三', '2027-01-12 08:30-10:30', '理教201', '闭卷', ''],
            [4831410, '程序设计实习', 1, '李四', '第19周 周三 14:00-16:00', '机房', '上机', '带学生证'],
            ['00130301', '线性代数', '01', '', '待定', '', '', ''],
            ['', '无课程号', '01', '', '2027-01-12 08:30-10:30', '', '', ''],
            [None, None, None, None, None, None, None, None],
        ], preamble=[['2026-2027学年第一学期期末考试安排'], []])
        output = self.run_command(path, '--term', '26-27-1')
        self.assertIn('done: created 2, updated 0, removed 0; skipped 2 row(s)', output)
        # Two preamble lines and the header precede the data rows.
        self.assertIn('skipped row 6: unreadable time', output)
        self.assertIn('skipped row 7: missing 课程号/课程名', output)
        self.assertEqual(self.rows(), [
            ('00130201', '01', '高等数学A（二）', datetime(2027, 1, 12, 8, 30),
             datetime(2027, 1, 12, 10, 30), '理教201', '闭卷'),
            ('04831410', '01', '程序设计实习', datetime(2027, 1, 13, 14, 0),
             datetime(2027, 1, 13, 16, 0), '机房', '上机'),
        ])
        exam = CourseExam.objects.get(course_code='04831410')
        self.assertEqual((exam.teacher, exam.note, exam.raw_time),
                         ('李四', '带学生证', '第19周 周三 14:00-16:00'))
        # Re-running changes nothing; a changed room is an update.
        output = self.run_command(path, '--term', '26-27-1')
        self.assertIn('created 0, updated 0, removed 0', output)
        path = self.workbook([
            ['00130201', '高等数学A（二）', '01', '张三', '2027-01-12 08:30-10:30', '理教301', '闭卷', ''],
        ], name='update.xlsx')
        output = self.run_command(path, '--term', '26-27-1')
        self.assertIn('created 0, updated 1, removed 0', output)
        self.assertEqual(CourseExam.objects.count(), 2)
        self.assertEqual(CourseExam.objects.get(course_code='00130201').room, '理教301')
        # --replace drops the term's rows first.
        output = self.run_command(path, '--term', '26-27-1', '--replace')
        self.assertIn('created 1, updated 0, removed 2', output)
        self.assertEqual(CourseExam.objects.count(), 1)

    def test_csv_with_separate_columns_and_other_terms(self):
        headers = ['学年学期', '课程编号', '课程名称', '教学班号', '任课教师', '考试日期',
                   '开始时间', '结束时间', '考场']
        path = self.csv_file([
            ['2026-2027学年第一学期', '00130201', '高等数学A（二）', '01', '张三', '2027/1/12',
             '8:30', '10:30', '理教201'],
            ['2026-2027学年第二学期', '00130202', '高等数学A（三）', '01', '张三', '2027/6/15',
             '8:30', '10:30', '理教201'],
            ['', '00130301', '线性代数', '', '', '1月14日（周四）', '14:00', '', '理教101'],
        ], headers)
        output = self.run_command(path, '--term', '26-27-1')
        self.assertIn('done: created 2, updated 0, removed 0; skipped 0 row(s), '
                      '1 row(s) of other term(s): 26-27-2 (1)', output)
        self.assertEqual(self.rows(), [
            ('00130201', '01', '高等数学A（二）', datetime(2027, 1, 12, 8, 30),
             datetime(2027, 1, 12, 10, 30), '理教201', ''),
            ('00130301', '', '线性代数', datetime(2027, 1, 14, 14, 0),
             datetime(2027, 1, 14, 16, 0), '理教101', ''),
        ])

    def test_errors(self):
        with self.assertRaises(CommandError) as ctx:
            self.run_command(self.workbook([]), '--term', 'no-such')
        self.assertIn('unknown term', str(ctx.exception))
        with self.assertRaises(CommandError) as ctx:
            self.run_command(self.workbook([], headers=['课程号', '课程名']), '--term', '26-27-1')
        self.assertIn('no header row', str(ctx.exception))
        with self.assertRaises(CommandError):
            self.run_command(str(Path(self.tmp.name) / 'missing.xlsx'), '--term', '26-27-1')
        with self.assertRaises(CommandError):
            self.run_command(str(Path(self.tmp.name) / 'missing.csv'), '--term', '26-27-1')
        with self.assertRaises(CommandError) as ctx:
            self.run_command(self.workbook([]), '--term', '26-27-1', '--sheet', 'nope')
        self.assertIn('not found', str(ctx.exception))
        with self.assertRaises(CommandError):
            self.run_command(self.csv_file([], HEADERS), '--term', '26-27-1', '--sheet', 'x')
        self.assertEqual(CourseExam.objects.count(), 0)
