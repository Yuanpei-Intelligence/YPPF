"""Fixture-based unit tests of ``timetable.sources.pku_parsers`` (no database)."""
from django.test import SimpleTestCase

from timetable.sources import pku_parsers as parsers
from timetable.sources.pku_parsers import LessonBlock
from timetable.tests.helpers import portal_payload, read_fixture


def _by_name(blocks, name):
    return [block for block in blocks if block.name == name]


class CellTextTests(SimpleTestCase):

    def test_portal_html_cell(self):
        cell = ('<td id="mon1" class="td-compact"><div><span style="font-size:12px;">'
                '高等数学A（二）(主)<br>上课信息：1-15周 每周 理教406  教师：束琳 备注：习题课'
                '<br>考试信息：20260618 星期四 上午 理教306</span></div></td>')
        (info,) = parsers.parse_course_cell_text(cell)
        self.assertEqual(info['name'], '高等数学A（二）')
        self.assertEqual(info['teacher'], '束琳')
        self.assertEqual(info['room'], '理教406')
        self.assertEqual((info['week_start'], info['week_end']), (1, 15))
        self.assertEqual(info['parity'], 0)
        self.assertEqual(info['note'], '习题课')
        self.assertNotIn('<br>', info['raw'])

    def test_missing_room_and_plain_newlines(self):
        (info,) = parsers.parse_course_cell_text(
            '体适能(主)\n上课信息：1-15周 每周   教师：郭思佳 备注：五四跑廊\n考试信息： ')
        self.assertEqual(info['name'], '体适能')
        self.assertEqual(info['room'], '')
        self.assertEqual(info['teacher'], '郭思佳')
        self.assertEqual(info['note'], '五四跑廊')

    def test_odd_weeks_and_tilde_range(self):
        (info,) = parsers.parse_course_cell_text(
            '程序设计实习(主)<br>上课信息：1~15周 单周 理教203  教师：郭炜 <br>考试信息：x')
        self.assertEqual(info['parity'], 1)
        self.assertEqual((info['week_start'], info['week_end']), (1, 15))
        self.assertEqual(info['room'], '理教203')
        self.assertEqual(info['teacher'], '郭炜')

    def test_several_info_lines_become_several_dicts(self):
        infos = parsers.parse_course_cell_text(
            '概率统计(主)\n上课信息：1-8周 每周 理教201 教师：张三\n'
            '上课信息：9-16周 双周 理教305 教师：张三')
        self.assertEqual(len(infos), 2)
        self.assertEqual([(i['week_start'], i['week_end'], i['parity'], i['room'])
                          for i in infos],
                         [(1, 8, 0, '理教201'), (9, 16, 2, '理教305')])

    def test_name_only_cell_defaults_to_full_term(self):
        (info,) = parsers.parse_course_cell_text('大学英语(双)')
        self.assertEqual(info['name'], '大学英语')
        self.assertEqual((info['week_start'], info['week_end']), (1, 16))

    def test_empty_cell(self):
        self.assertEqual(parsers.parse_course_cell_text(''), [])
        self.assertEqual(parsers.parse_course_cell_text('<span></span>'), [])

    def test_clean_course_name_keeps_real_parentheses(self):
        self.assertEqual(parsers.clean_course_name('高等数学A（二）(主)'), '高等数学A（二）')
        self.assertEqual(parsers.clean_course_name('线性代数（辅）(慕课)'), '线性代数')
        self.assertEqual(parsers.clean_course_name('  微积分(外) '), '微积分')

    def test_ascii_colon_and_teacher_variants(self):
        (info,) = parsers.parse_course_cell_text(
            '物理(主)\n上课信息:2-16周 每周 二教107 教师:王五 备注:无')
        self.assertEqual(info['teacher'], '王五')
        self.assertEqual(info['room'], '二教107')
        self.assertEqual(info['week_start'], 2)

    def test_several_courses_in_one_cell_keep_their_own_exam(self):
        infos = parsers.parse_course_cell_text(
            "<font color = 'red'><b>课程甲(主)<br>上课信息：1-15周 单周 二教411  教师：教师甲<br>"
            '考试信息：20260618 星期四 上午 二教411<br>课程乙(主)<br>'
            '上课信息：1-8周 双周 二教410  教师：教师乙<br>'
            '上课信息：9-15周 每周 二教412  教师：教师乙<br>考试信息： </b></font>')
        self.assertEqual([(i['name'], i['week_start'], i['parity'], i['room'], i['teacher'])
                          for i in infos],
                         [('课程甲', 1, 1, '二教411', '教师甲'),
                          ('课程乙', 1, 2, '二教410', '教师乙'),
                          ('课程乙', 9, 0, '二教412', '教师乙')])
        self.assertEqual([(i['exam_date'], i['exam_period'], i['exam_room']) for i in infos],
                         [('2026-06-18', '上午', '二教411'), ('', '', ''), ('', '', '')])

    def test_exam_of_a_name_only_course_and_trailing_text(self):
        (info,) = parsers.parse_course_cell_text(
            '课程丙(主)\n上课信息：2-16周 每周 理教101\n考试信息：2027-01-12 周二 晚上 理教101\n'
            '续行的说明')
        self.assertEqual((info['name'], info['exam_date'], info['exam_period'], info['exam_room']),
                         ('课程丙', '2027-01-12', '晚上', '理教101'))
        (only,) = parsers.parse_course_cell_text('大学英语(双)\n考试信息：20260620 星期六 下午 ')
        self.assertEqual((only['week_start'], only['week_end'], only['exam_date'],
                          only['exam_period'], only['exam_room']),
                         (1, 16, '2026-06-20', '下午', ''))

    def test_parse_exam_info(self):
        self.assertEqual(parsers.parse_exam_info('20260618 星期四 上午 二教411'),
                         ('2026-06-18', '上午', '二教411'))
        self.assertEqual(parsers.parse_exam_info('考试信息：20251229 星期一 下午 二教301,二教309'),
                         ('2025-12-29', '下午', '二教301,二教309'))
        self.assertEqual(parsers.parse_exam_info('20260621 星期七 晚上'), ('2026-06-21', '晚上', ''))
        self.assertEqual(parsers.parse_exam_info('2027/1/12 周2 理教101'), ('2027-01-12', '', '理教101'))
        for blank in ('', ' ', '考试信息： ', 'x', '20261340 上午 理教101'):
            with self.subTest(blank=blank):
                self.assertEqual(parsers.parse_exam_info(blank), ('', '', ''))


class PortalJsonTests(SimpleTestCase):

    def setUp(self):
        self.blocks = parsers.parse_portal_course_json(portal_payload())

    def test_consecutive_sections_merge(self):
        (math,) = _by_name(self.blocks, '高等数学A（二）')
        self.assertEqual((math.weekday, math.start_section, math.end_section), (1, 1, 2))
        self.assertEqual((math.week_start, math.week_end, math.parity), (1, 15, 0))
        self.assertEqual(math.room, '理教406')
        self.assertEqual(math.teacher, '束琳')
        self.assertEqual(math.note, '习题课')

    def test_missing_room_and_missing_parity_key(self):
        (pe,) = _by_name(self.blocks, '体适能')
        self.assertEqual((pe.weekday, pe.start_section, pe.end_section), (2, 3, 4))
        self.assertEqual(pe.room, '')
        (linear,) = _by_name(self.blocks, '线性代数')
        self.assertEqual((linear.weekday, linear.start_section, linear.end_section), (4, 3, 4))
        self.assertEqual((linear.week_start, linear.week_end), (1, 16))

    def test_parity_from_text_and_from_cell_field(self):
        (prog,) = _by_name(self.blocks, '程序设计实习')
        self.assertEqual(prog.parity, 1)
        self.assertEqual((prog.weekday, prog.start_section, prog.end_section), (3, 5, 6))
        (english,) = _by_name(self.blocks, '大学英语')
        self.assertEqual(english.parity, 2)
        self.assertEqual((english.start_section, english.end_section), (7, 8))
        self.assertEqual((english.week_start, english.week_end), (1, 16))

    def test_several_info_lines_give_several_blocks(self):
        stats = _by_name(self.blocks, '概率统计')
        self.assertEqual(len(stats), 2)
        for block in stats:
            self.assertEqual((block.weekday, block.start_section, block.end_section), (5, 10, 11))
        self.assertEqual({(b.week_start, b.week_end, b.parity, b.room) for b in stats},
                         {(1, 8, 0, '理教201'), (9, 16, 2, '理教305')})

    def test_block_count_and_order(self):
        self.assertEqual(len(self.blocks), 7)
        self.assertEqual([b.weekday for b in self.blocks], sorted(b.weekday for b in self.blocks))

    def test_exam_info_per_course(self):
        (math,) = _by_name(self.blocks, '高等数学A（二）')
        self.assertEqual((math.exam_date, math.exam_period, math.exam_room),
                         ('2026-06-18', '上午', '理教306'))
        (prog,) = _by_name(self.blocks, '程序设计实习')
        self.assertEqual((prog.exam_date, prog.exam_period, prog.exam_room),
                         ('2026-06-12', '下午', '理教203'))
        for name in ('体适能', '线性代数', '大学英语'):
            (block,) = _by_name(self.blocks, name)
            self.assertEqual((block.exam_date, block.exam_period, block.exam_room), ('', '', ''))

    def test_accepts_json_string(self):
        blocks = parsers.parse_portal_course_json(read_fixture('portal_course.json'))
        self.assertEqual(len(blocks), 7)

    def test_rejects_failed_or_malformed_payload(self):
        with self.assertRaises(ValueError):
            parsers.parse_portal_course_json({'success': False, 'remark': '未登录'})
        with self.assertRaises(ValueError):
            parsers.parse_portal_course_json({'foo': 'bar'})
        with self.assertRaises(ValueError):
            parsers.parse_portal_course_json(['not', 'an', 'object'])

    def test_tolerates_plain_string_cells_and_digit_section_numbers(self):
        payload = {'course': [
            {'timeNum': '第1节', 'mon': '体育\n上课信息：1-16周 每周 五四操场 教师：李教练'},
            {'timeNum': 2, 'mon': {'courseName': '体育\n上课信息：1-16周 每周 五四操场 教师：李教练'}},
            {'timeNum': '第三节', 'mon': {'courseName': '体育\n上课信息：1-16周 每周 五四操场 教师：李教练'}},
            {'timeNum': '午休'},
        ]}
        (block,) = parsers.parse_portal_course_json(payload)
        self.assertEqual((block.start_section, block.end_section), (1, 3))
        self.assertEqual(block.room, '五四操场')


class PublicQueryCourseTableTests(SimpleTestCase):
    """
    ``publicQuery`` ``getCourseInfo.do`` with 考试信息 and a red conflict cell;
    the fixture follows a public sample of that payload with teachers and
    remarks replaced.
    """

    def setUp(self):
        self.blocks = parsers.parse_portal_course_json(read_fixture('publicquery_course.json'))

    def test_conflict_cell_keeps_each_course_with_its_own_exam(self):
        tuesday = [b for b in self.blocks if (b.weekday, b.start_section) == (2, 1)]
        self.assertEqual(
            [(b.name, b.end_section, b.parity, b.room, b.teacher, b.note) for b in tuesday],
            [('量子力学', 2, 1, '二教411', '教师甲', '示例备注一。'),
             ('量子力学习题', 2, 2, '二教410', '教师甲', '示例备注二。')])
        self.assertEqual([(b.exam_date, b.exam_period, b.exam_room) for b in tuesday],
                         [('2026-06-18', '上午', '二教411'), ('', '', '')])
        for block in self.blocks:
            self.assertNotIn('<', block.name)
            self.assertNotIn('font', block.raw)

    def test_blank_exam_line_and_sunday_exam(self):
        (relativity,) = _by_name(self.blocks, '广义相对论')
        self.assertEqual((relativity.weekday, relativity.start_section, relativity.end_section),
                         (2, 3, 4))
        self.assertEqual((relativity.room, relativity.note), ('', '研本合上；上课地点：理教309'))
        self.assertEqual((relativity.exam_date, relativity.exam_period, relativity.exam_room),
                         ('', '', ''))
        (solid,) = _by_name(self.blocks, '固体物理学')
        self.assertEqual((solid.exam_date, solid.exam_period, solid.exam_room),
                         ('2026-06-21', '下午', '二教505'))

    def test_block_count_and_one_course_on_two_days(self):
        self.assertEqual(len(self.blocks), 5)
        quantum = _by_name(self.blocks, '量子力学')
        self.assertEqual([(b.weekday, b.start_section, b.end_section, b.parity) for b in quantum],
                         [(2, 1, 2, 1), (4, 3, 4, 0)])
        self.assertEqual({b.exam_date for b in quantum}, {'2026-06-18'})
        self.assertEqual(parsers.detect_format(read_fixture('publicquery_course.json')),
                         'portal_json')


class PortalHtmlTests(SimpleTestCase):

    def setUp(self):
        self.blocks = parsers.parse_portal_html(read_fixture('portal_page.html'))

    def test_cells_are_located_by_id(self):
        (math,) = _by_name(self.blocks, '高等数学A（二）')
        self.assertEqual((math.weekday, math.start_section, math.end_section), (1, 1, 2))
        (history,) = _by_name(self.blocks, '中国近现代史纲要')
        self.assertEqual((history.weekday, history.start_section, history.end_section), (4, 10, 11))
        self.assertEqual((history.week_start, history.week_end), (2, 16))
        self.assertEqual(history.room, '二教107')

    def test_all_courses_found(self):
        names = sorted({block.name for block in self.blocks})
        self.assertEqual(names, ['中国近现代史纲要', '体适能', '概率统计', '程序设计实习', '高等数学A（二）'])
        self.assertEqual(len(self.blocks), 6)

    def test_detect_format(self):
        self.assertEqual(parsers.detect_format(read_fixture('portal_page.html')), 'portal_html')


class ElectiveTableTests(SimpleTestCase):

    def test_html_table(self):
        blocks = parsers.parse_elective_table(read_fixture('elective_table.html'))
        self.assertEqual(len(blocks), 4)
        math = _by_name(blocks, '高等数学A（二）')
        self.assertEqual(len(math), 2)
        self.assertEqual([(b.weekday, b.start_section, b.end_section) for b in math],
                         [(1, 1, 2), (3, 3, 4)])
        self.assertEqual({b.teacher for b in math}, {'束琳'})
        self.assertEqual({b.class_no for b in math}, {'01'})
        self.assertEqual({b.room for b in math}, {'理教306'})
        (prog,) = _by_name(blocks, '程序设计实习')
        self.assertEqual((prog.weekday, prog.parity, prog.start_section, prog.end_section), (5, 1, 7, 8))
        (dance,) = _by_name(blocks, '体育舞蹈')
        self.assertEqual((dance.weekday, dance.parity, dance.week_start, dance.week_end), (7, 2, 2, 15))
        self.assertEqual(dance.room, '邱德拔体育馆')

    def test_unselected_rows_skipped(self):
        blocks = parsers.parse_elective_table(read_fixture('elective_table.html'))
        self.assertEqual(_by_name(blocks, '艺术史'), [])

    def test_plain_text(self):
        blocks = parsers.parse_elective_table(read_fixture('elective_plain.txt'))
        math = _by_name(blocks, '高等数学A（二）')
        self.assertEqual([(b.weekday, b.start_section, b.end_section, b.room) for b in math],
                         [(1, 1, 2, '理教306'), (3, 3, 4, '理教306')])
        (prog,) = _by_name(blocks, '程序设计实习')
        self.assertEqual((prog.weekday, prog.parity), (5, 1))
        linear = _by_name(blocks, '线性代数')
        self.assertEqual(len(linear), 2)
        self.assertEqual({(b.weekday, b.parity) for b in linear}, {(2, 0), (4, 2)})
        self.assertEqual({b.teacher for b in linear}, {'李四'})
        self.assertEqual({b.class_no for b in linear}, {'01'})
        (dance,) = _by_name(blocks, '体育舞蹈')
        self.assertEqual((dance.weekday, dance.start_section, dance.end_section), (7, 5, 6))
        self.assertEqual(_by_name(blocks, '艺术史'), [])
        self.assertEqual(_by_name(blocks, '选课结果'), [])

    def test_detect_format(self):
        self.assertEqual(parsers.detect_format(read_fixture('elective_table.html')), 'elective')
        self.assertEqual(parsers.detect_format(read_fixture('elective_plain.txt')), 'elective')
        self.assertEqual(parsers.detect_format(read_fixture('portal_course.json')), 'portal_json')
        self.assertEqual(parsers.detect_format('hello world'), 'unknown')
        self.assertEqual(parsers.detect_format(''), 'unknown')

    def test_parse_text_dispatch(self):
        fmt, blocks = parsers.parse_text(read_fixture('elective_table.html'))
        self.assertEqual(fmt, 'elective')
        self.assertEqual(len(blocks), 4)
        fmt, blocks = parsers.parse_text(read_fixture('portal_course.json'))
        self.assertEqual(fmt, 'portal_json')
        self.assertEqual(len(blocks), 7)
        self.assertEqual(parsers.parse_text('nothing here'), ('unknown', []))


class ExternalKeyTests(SimpleTestCase):

    def test_key_is_sha1_over_identity_fields(self):
        block = LessonBlock(name='高数', weekday=1, start_section=1, end_section=2,
                            week_start=1, week_end=16, parity=0, room='理教201')
        key = parsers.external_key(block)
        self.assertEqual(len(key), 40)
        same_other_room = LessonBlock(name=' 高数 ', weekday=1, start_section=1,
                                      end_section=2, week_start=1, week_end=16,
                                      parity=0, room='理教305', teacher='X')
        self.assertEqual(parsers.external_key(same_other_room), key)
        moved = LessonBlock(name='高数', weekday=2, start_section=1, end_section=2,
                            week_start=1, week_end=16, parity=0)
        self.assertNotEqual(parsers.external_key(moved), key)
        odd = LessonBlock(name='高数', weekday=1, start_section=1, end_section=2,
                          week_start=1, week_end=16, parity=1)
        self.assertNotEqual(parsers.external_key(odd), key)
