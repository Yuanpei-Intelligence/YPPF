"""
Graduate ``retrScores.do`` rows in the shape seen with a real account on
2026-09-10 (keys cj, cjjlfsm, hgbz, kch, kclb, kcmc, khfsm, xf, xnd, xq,
yjscjbh; top-level xh / xm next to scoreLists). Values here are made up.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from academic_record.parsers import parse_scores

PAYLOAD = {
    'success': True,
    'xslb': 'yjs',
    'xh': '2400000000',
    'xm': '研究生乙',
    'scoreLists': [
        {'yjscjbh': '12', 'kch': '00000001', 'kcmc': '课程甲', 'kclb': '必修', 'xf': '3',
         'cj': 'A+', 'hgbz': '合格', 'khfsm': '考试', 'cjjlfsm': '等级制2017',
         'xnd': '24-25', 'xq': '1'},
        {'yjscjbh': '7', 'kch': '00000002', 'kcmc': '课程乙', 'kclb': '选修', 'xf': '2',
         'cj': 'B-', 'hgbz': '', 'khfsm': '考试', 'cjjlfsm': '等级制2017',
         'xnd': '24-25', 'xq': '2'},
        {'yjscjbh': '30', 'kch': '00000003', 'kcmc': '课程丙', 'kclb': '必修', 'xf': '1',
         'cj': 'P', 'hgbz': '合格', 'khfsm': '考试', 'cjjlfsm': '等级制2017',
         'xnd': '25-26', 'xq': '1'},
    ],
}


class GraduatePayloadShapeTests(SimpleTestCase):

    def test_rows_terms_types_and_letter_grades(self):
        rows = [row for term in parse_scores(PAYLOAD) for row in term.rows]
        self.assertEqual(len(rows), 3)
        by_name = {row.name: row for row in rows}
        first = by_name['课程甲']
        self.assertEqual(first.term_code, '24-25-1')
        self.assertEqual(first.course_code, '00000001')
        self.assertEqual(first.course_type, '必修')
        self.assertEqual(first.credits, Decimal('3.0'))
        self.assertEqual(first.score, 'A+')
        self.assertIsNone(first.score_numeric)
        self.assertEqual(by_name['课程乙'].term_code, '24-25-2')
        self.assertEqual(by_name['课程丙'].term_code, '25-26-1')

    def test_identity_fields_never_reach_rows(self):
        for term in parse_scores(PAYLOAD):
            for row in term.rows:
                self.assertNotIn('xh', row.raw)
                self.assertNotIn('xm', row.raw)
                self.assertNotIn('2400000000', repr(row))
                self.assertNotIn('研究生乙', repr(row))
