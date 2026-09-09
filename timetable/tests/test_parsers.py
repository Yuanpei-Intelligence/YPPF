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
