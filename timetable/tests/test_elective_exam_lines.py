"""
Exam lines of the elective 选课结果 page, in the shape seen on an undergraduate
account on 2026-09-10 (13 cells per row; the 教室信息 cell ends with
"考试时间：YYYYMMDD上午|下午|晚上；" or an undated exam remark). Values are made up.
"""
from django.test import SimpleTestCase

from timetable.sources import pku_parsers


def _row(code, name, teacher, class_no, room_info):
    cells = [code, name, '专业课', '2.0', '2.0', teacher, class_no, '某学院', room_info,
             '学分课', '已选上', '10.0.0.1', '2026-09-01 10:00:00']
    return '<tr class="datagrid-odd">' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>'


HTML = (
    '<table class="datagrid"><tr class="datagrid-header"><th>课程号</th><th>课程名</th></tr>'
    + _row('00000001', '课程甲', '教师甲(教授)', '1',
           '1~16周 每周周三7~8节 二教101<br>考试时间：20270112晚上；')
    + _row('00000002', '课程乙', '教师乙(讲师)', '2',
           '1~16周 每周周二3~4节 二教102<br>1~16周 双周周四5~6节 二教103<br>考试时间：20270114上午；')
    + _row('00000003', '课程丙', '教师丙(副教授)', '1',
           '1~16周 每周周一10~12节 三教201<br>考试方式：论文、课堂报告')
    + _row('00000004', '课程丁', '教师丁(教授)', '1', '考试方式：论文')
    + '</table>'
)


class ElectiveExamLineTests(SimpleTestCase):

    def test_dated_exam_line_fills_every_block_of_the_course(self):
        fmt, blocks = pku_parsers.parse_text(HTML)
        self.assertEqual(fmt, 'elective')
        by_name = {}
        for block in blocks:
            by_name.setdefault(block.name, []).append(block)
        self.assertEqual(set(by_name), {'课程甲', '课程乙', '课程丙'})  # 课程丁 has no time
        (first,) = by_name['课程甲']
        self.assertEqual((first.exam_date, first.exam_period, first.exam_room),
                         ('2027-01-12', '晚上', ''))
        self.assertEqual(first.room, '二教101')
        second = by_name['课程乙']
        self.assertEqual(len(second), 2)
        self.assertEqual({(b.exam_date, b.exam_period) for b in second}, {('2027-01-14', '上午')})
        self.assertEqual({b.room for b in second}, {'二教102', '二教103'})

    def test_undated_exam_remark_becomes_the_note(self):
        _fmt, blocks = pku_parsers.parse_text(HTML)
        (third,) = [b for b in blocks if b.name == '课程丙']
        self.assertEqual(third.exam_date, '')
        self.assertEqual(third.note, '考试方式：论文、课堂报告')
        self.assertEqual(third.room, '三教201')

    def test_plain_text_exam_line_attaches_to_the_previous_course(self):
        text = ('选课结果\n课程戊\n1~16周 每周周二3~4节 理教201\n考试时间：20270115下午；\n'
                '课程己\n1~16周 单周周五7~8节 理教203\n')
        blocks = pku_parsers.parse_elective_table(text)
        by_name = {b.name: b for b in blocks}
        self.assertEqual(set(by_name), {'课程戊', '课程己'})
        self.assertEqual((by_name['课程戊'].exam_date, by_name['课程戊'].exam_period),
                         ('2027-01-15', '下午'))
        self.assertEqual(by_name['课程己'].exam_date, '')
