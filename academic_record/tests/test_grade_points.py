"""
Grade points of publicQuery undergraduate rows (no 绩点 column) and the raw
fields never kept, in the row shape seen on 2026-09-10. Values are made up.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from academic_record.parsers import grade_point, parse_row, parse_scores, summary


def _row(score, credits='2', **extra):
    row = {'kch': '00000001', 'kcmc': '课程', 'kclb': '13', 'kclbmc': '专业必修', 'xf': credits,
           'xqcj': score, 'cjjlfs': '百分制', 'xnd': '25-26', 'xq': '1',
           'skjsxm': '0000000000-教师$某学院$教授', 'skjszgh': '0000000000(00001)',
           'ywmc': 'Course', 'bkcjbh': 'bkcj0001'}
    row.update(extra)
    return row


class GradePointTests(SimpleTestCase):

    def test_formula(self):
        self.assertEqual(grade_point(100), 4.0)
        self.assertEqual(grade_point(60), 1.0)
        self.assertEqual(grade_point(59.5), 0.0)
        self.assertAlmostEqual(grade_point(85), 4 - 3 * 15 ** 2 / 1600)
        self.assertEqual(grade_point(105), 4.0)

    def test_publicquery_rows_get_a_derived_grade_point(self):
        row = parse_row(_row('85'))
        self.assertAlmostEqual(row.gpa, round(4 - 3 * 225 / 1600, 4))
        self.assertIsNone(parse_row(_row('合格', cjjlfs='合格制')).gpa)
        self.assertIsNone(parse_row(_row('P', cjjlfs='')).gpa)
        # A row that carries the portal's own 绩点 keeps it, even when blank.
        self.assertEqual(parse_row(_row('85', jd='3.7')).gpa, 3.7)
        self.assertIsNone(parse_row(_row('85', jd='')).gpa)

    def test_summary_weights_numeric_rows_only(self):
        payload = {'success': True, 'xslb': 'bks', 'gpa': {'gpa': '3.000', 'xxxf': '4'},
                   'cjxx': [{'xnd': '25-26', 'xq': '1',
                             'list': [_row('100', '2'), _row('60', '2'), _row('合格', '1', cjjlfs='合格制')]}]}
        rows = [row for term in parse_scores(payload) for row in term.rows]
        self.assertEqual(summary(rows), {'credits': 5.0, 'gpa': 2.5})

    def test_teacher_ids_never_reach_raw(self):
        row = parse_row(_row('90'))
        self.assertNotIn('skjsxm', row.raw)
        self.assertNotIn('skjszgh', row.raw)
        self.assertEqual(row.raw.get('ywmc'), 'Course')
        self.assertEqual(row.course_type, '专业必修')
        self.assertEqual(row.credits, Decimal('2.0'))
