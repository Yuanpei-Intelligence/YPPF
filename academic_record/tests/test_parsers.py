"""Parser tests: nested and flattened payloads, tolerance, summary math."""
import json
from decimal import Decimal

from django.test import SimpleTestCase

from academic_record.parsers import (
    UNKNOWN_TERM,
    GradeRow,
    TermScores,
    has_score_list,
    is_graduate_payload,
    parse_row,
    parse_scores,
    summary,
    term_code_of,
)
from academic_record.tests.helpers import flat_payload, make_row, scores_payload

# Hand-computed from fixtures/portal_scores.json.
TERM1_CREDITS = 15.0            # 5 + 2 + 1 + 4 + 2 + 1
TERM1_GPA = 3.41                # (5*3.9 + 4*3.4 + 1*1.0) / 10
TERM2_CREDITS = 2.0
TERM2_GPA = 3.6
ALL_CREDITS = 17.0
ALL_GPA = 3.442                 # (34.1 + 7.2) / 12


class ParseScoresTests(SimpleTestCase):

    def test_nested_payload(self):
        terms = parse_scores(scores_payload())
        self.assertEqual([term.term_code for term in terms], ['25-26-1', '25-26-2'])
        first, second = terms
        self.assertEqual(
            [row.name for row in first.rows],
            ['高等数学A（一）', '军事理论', '体育', '线性代数', '退课的课', ''])
        math = first.rows[0]
        self.assertEqual(math, GradeRow(
            term_code='25-26-1', name='高等数学A（一）', course_code='00132301',
            class_no='01', course_type='专业必修', credits=Decimal('5.0'),
            score='92', score_numeric=92.0, gpa=3.9, raw={'bkcj': ''}))
        by_code = {row.course_code: row for row in first.rows}
        self.assertEqual(by_code['00000002'].name, '')
        self.assertEqual(by_code['00000002'].gpa, 1.0)
        self.assertEqual([row.name for row in second.rows], ['大学英语', '通选课'])
        english = second.rows[0]
        self.assertEqual(english.credits, Decimal('2.0'))
        self.assertEqual(english.score_numeric, 88.5)
        self.assertEqual(english.gpa, 3.6)
        self.assertEqual(english.course_type, '公共必修')
        self.assertEqual(english.raw, {'extra': {'nested': True}})
        blank = second.rows[1]
        self.assertEqual((blank.course_code, blank.credits, blank.score,
                          blank.score_numeric, blank.gpa), ('', None, '', None, None))

    def test_flattened_payload_matches_nested(self):
        self.assertEqual(parse_scores(flat_payload()), parse_scores(scores_payload()))

    def test_flattened_rows_group_by_term_in_first_seen_order(self):
        payload = {'cjxx': [
            {'kcmc': 'A', 'xnd': '25-26', 'xq': '1'},
            {'kcmc': 'B', 'xnd': '24-25', 'xq': '2'},
            {'kcmc': 'C', 'xnd': '25-26', 'xq': '1'},
        ]}
        terms = parse_scores(payload)
        self.assertEqual([(t.term_code, [r.name for r in t.rows]) for t in terms],
                         [('25-26-1', ['A', 'C']), ('24-25-2', ['B'])])
        self.assertEqual(terms[0].rows[0].raw, {})

    def test_non_numeric_scores(self):
        for value, text in (('P', 'P'), ('合格', '合格'), ('W', 'W'), ('', ''),
                            (None, ''), ('nan', 'nan'), ('inf', 'inf'),
                            (True, 'True'), ('优秀', '优秀')):
            with self.subTest(value=value):
                row = parse_row({'kcmc': '课', 'xqcj': value, 'jd': value}, '25-26-1')
                self.assertEqual(row.score, text)
                self.assertIsNone(row.score_numeric)
                self.assertIsNone(row.gpa)

    def test_numbers_as_strings_or_numbers(self):
        as_text = parse_row({'kcmc': '课', 'xf': '2.0', 'xqcj': '85', 'jd': '3.6'}, 't')
        as_number = parse_row({'kcmc': '课', 'xf': 2, 'xqcj': 85, 'jd': 3.6}, 't')
        self.assertEqual(as_text.credits, Decimal('2.0'))
        self.assertEqual(as_number.credits, Decimal('2.0'))
        self.assertEqual((as_text.score, as_text.score_numeric), ('85', 85.0))
        self.assertEqual((as_number.score, as_number.score_numeric), ('85', 85.0))
        self.assertEqual(as_text.gpa, as_number.gpa)
        padded = parse_row({'kcmc': '课', 'xqcj': ' 90.5 '}, 't')
        self.assertEqual(padded.score_numeric, 90.5)

    def test_missing_keys(self):
        self.assertIsNone(parse_row({}, 't'))
        self.assertIsNone(parse_row({'xf': '2', 'xqcj': '90'}, 't'))
        self.assertIsNone(parse_row({'kcmc': '', 'kch': None}, 't'))
        self.assertIsNone(parse_row('kcmc', 't'))
        self.assertIsNone(parse_row(None, 't'))
        row = parse_row({'kcmc': '只有名字'}, '25-26-1')
        self.assertEqual(row, GradeRow(term_code='25-26-1', name='只有名字'))
        row = parse_row({'kch': '00000001'}, '25-26-1')
        self.assertEqual((row.name, row.course_code), ('', '00000001'))

    def test_candidate_keys_and_raw(self):
        # Real undergraduate rows carry the category name in kclbmc and its
        # numeric code in kclb (Treehole score_v2 sample: "任选" / "30").
        row = parse_row({'kcmc': '课', 'bh': '02', 'kclbmc': '任选', 'kclb': '30',
                         'foo': 1, 'bar': [1, 2]}, 't')
        self.assertEqual(row.class_no, '02')
        self.assertEqual(row.course_type, '任选')
        # Only the key that was used leaves ``raw``.
        self.assertEqual(row.raw, {'kclb': '30', 'foo': 1, 'bar': [1, 2]})
        # Graduate rows only have a readable kclb.
        graduate = parse_row({'kcmc': '课', 'kclb': '学位课'}, 't')
        self.assertEqual(graduate.course_type, '学位课')

    def test_values_are_cut_to_column_lengths(self):
        row = parse_row({'kcmc': '名' * 100, 'kch': 'c' * 40, 'bjh': '1' * 12,
                         'kclb': '类' * 40, 'xqcj': 'x' * 20}, 'y' * 20)
        self.assertEqual(len(row.name), 80)
        self.assertEqual(len(row.course_code), 32)
        self.assertEqual(len(row.class_no), 8)
        self.assertEqual(len(row.course_type), 32)
        self.assertEqual(len(row.score), 16)
        self.assertEqual(len(row.term_code), 20)  # given by the caller
        flattened = parse_row({'kcmc': '课', 'xnd': 'y' * 20, 'xq': '1'})
        self.assertEqual(len(flattened.term_code), 16)

    def test_credits_are_rounded_and_bounded(self):
        cases = (('2.25', Decimal('2.3')), ('0.5', Decimal('0.5')),
                 ('3', Decimal('3.0')), ('999.9', Decimal('999.9')),
                 ('1000', None), ('abc', None), ('', None), (None, None),
                 ('nan', None), (True, None))
        for value, expected in cases:
            with self.subTest(value=value):
                row = parse_row({'kcmc': '课', 'xf': value}, 't')
                self.assertEqual(row.credits, expected)

    def test_term_code_of(self):
        self.assertEqual(term_code_of('25-26', '1'), '25-26-1')
        self.assertEqual(term_code_of(' 25-26 ', 2), '25-26-2')
        self.assertEqual(term_code_of('25-26', None), '25-26')
        self.assertEqual(term_code_of(None, '1'), '1')
        self.assertEqual(term_code_of(None, None), '')
        self.assertEqual(term_code_of('', ''), '')

    def test_malformed_payloads(self):
        for payload in (None, [], 'x', 42, {}, {'cjxx': None}, {'cjxx': {}},
                        {'cjxx': 'x'}, {'cjxx': [None, 1, 'x', []]}):
            with self.subTest(payload=payload):
                self.assertEqual(parse_scores(payload), [])

    def test_terms_without_rows_are_omitted(self):
        payload = {'cjxx': [
            {'xnd': '24-25', 'xq': '2', 'list': []},
            {'xnd': '24-25', 'xq': '1', 'list': [{}, 'x', {'xf': '2'}]},
            {'xnd': '23-24', 'xq': '1', 'list': 'not a list'},
        ]}
        self.assertEqual(parse_scores(payload), [])

    def test_block_term_wins_over_row_term(self):
        payload = {'cjxx': [{'xnd': '25-26', 'xq': '1', 'list': [
            {'kcmc': '课', 'xnd': '20-21', 'xq': '2'}]}]}
        terms = parse_scores(payload)
        self.assertEqual(terms[0].term_code, '25-26-1')
        self.assertEqual(terms[0].rows[0].raw, {})

    def test_as_dict_has_api_shape_without_raw(self):
        row = make_row(raw={'secret': 'SENTINEL'})
        data = row.as_dict()
        self.assertEqual(set(data), {
            'term_code', 'course_code', 'class_no', 'name', 'course_type',
            'credits', 'score', 'score_numeric', 'gpa'})
        self.assertEqual(data['credits'], 2.0)
        self.assertIsInstance(data['credits'], float)
        self.assertNotIn('SENTINEL', json.dumps(data, ensure_ascii=False))
        self.assertIsNone(make_row(credits=None).as_dict()['credits'])
        self.assertEqual(row.key, ('25-26-1', '00000000', '课程'))


class GraduateScoresTests(SimpleTestCase):
    """``xslb == 'yjs'``: rows under ``scoreLists``; their term keys are not confirmed."""

    @staticmethod
    def payload():
        return {
            'success': True, 'xslb': 'yjs', 'grade': '2025', 'gpa': '3.9',
            'jbxx': {'xm': '研究生甲', 'xh': '2500000000'},
            'scoreLists': [
                {'kcmc': '高等量子力学', 'xf': '4', 'cj': '91', 'kclb': '学位课', 'hgbz': '是',
                 'xnd': '25-26', 'xq': '1'},
                {'kcmc': '学术规范', 'xf': 1, 'cj': '合格', 'kclbmc': '必修环节', 'hgbz': '是',
                 'xndxq': '25-26-2'},
                {'kcmc': '专业英语', 'xf': '2', 'xqcj': '88', 'kclb': '选修课'},
                {'kch': '', 'kcmc': '', 'cj': '90'},
                'not a row',
            ],
        }

    def test_score_lists_rows(self):
        terms = parse_scores(self.payload())
        self.assertEqual([term.term_code for term in terms], ['25-26-1', '25-26-2', UNKNOWN_TERM])
        (quantum,), (ethics,), (english,) = (term.rows for term in terms)
        self.assertEqual(quantum, GradeRow(
            term_code='25-26-1', name='高等量子力学', course_type='学位课',
            credits=Decimal('4.0'), score='91', score_numeric=91.0, gpa=None,
            raw={'hgbz': '是'}))
        self.assertEqual((ethics.course_type, ethics.credits, ethics.score, ethics.score_numeric,
                          ethics.raw), ('必修环节', Decimal('1.0'), '合格', None, {'hgbz': '是'}))
        self.assertEqual((english.term_code, english.score, english.raw), (UNKNOWN_TERM, '88', {}))
        # The personal block is never read.
        dumped = repr(terms)
        self.assertNotIn('研究生甲', dumped)
        self.assertNotIn('2500000000', dumped)

    def test_nested_blocks_and_cjxx_rows_of_a_graduate(self):
        payload = {
            'xslb': 'yjs',
            'cjxx': [{'kcmc': '本科课', 'xnd': '21-22', 'xq': '1', 'xqcj': '80'}],
            'scoreLists': [
                {'xnd': '25-26', 'xq': '1', 'list': [{'kcmc': '讨论班', 'cj': 'P'}]},
                {'list': [{'kcmc': '自带学期', 'cj': '85', 'xndxq': '24-25-2'},
                          {'kcmc': '无学期', 'cj': '86'}]},
            ],
        }
        self.assertEqual(
            [(term.term_code, [row.name for row in term.rows]) for term in parse_scores(payload)],
            [('21-22-1', ['本科课']), ('25-26-1', ['讨论班']), ('24-25-2', ['自带学期']),
             (UNKNOWN_TERM, ['无学期'])])

    def test_undergraduate_payloads_ignore_score_lists(self):
        payload = scores_payload()
        payload.update(xslb='bks', scoreLists=[{'kcmc': '不该出现', 'cj': '90'}])
        self.assertEqual(parse_scores(payload), parse_scores(scores_payload()))
        self.assertEqual(parse_scores({'scoreLists': [{'kcmc': 'x', 'cj': '1'}]}), [])

    def test_payload_kind_and_score_list_detection(self):
        self.assertTrue(is_graduate_payload({'xslb': 'yjs'}))
        self.assertFalse(is_graduate_payload({'xslb': 'bks'}))
        self.assertFalse(is_graduate_payload(['yjs']))
        self.assertTrue(has_score_list({'cjxx': []}))
        self.assertTrue(has_score_list({'xslb': 'yjs', 'scoreLists': []}))
        self.assertFalse(has_score_list({'xslb': 'bks', 'scoreLists': []}))
        self.assertFalse(has_score_list({'xslb': 'yjs'}))
        self.assertFalse(has_score_list({'xslb': 'yjs', 'scoreLists': 'x'}))
        self.assertFalse(has_score_list(None))


class SummaryTests(SimpleTestCase):

    def test_summary_of_fixture(self):
        first, second = parse_scores(scores_payload())
        self.assertEqual(summary(first.rows),
                         {'credits': TERM1_CREDITS, 'gpa': TERM1_GPA})
        self.assertEqual(summary(second.rows),
                         {'credits': TERM2_CREDITS, 'gpa': TERM2_GPA})
        self.assertEqual(summary(first.rows + second.rows),
                         {'credits': ALL_CREDITS, 'gpa': ALL_GPA})

    def test_summary_without_rows(self):
        self.assertEqual(summary([]), {'credits': 0.0, 'gpa': None})
        self.assertEqual(summary(TermScores('t').rows), {'credits': 0.0, 'gpa': None})

    def test_rows_missing_credits_or_gpa(self):
        rows = [make_row(name='a', credits=Decimal('2.0'), gpa=None),
                make_row(name='b', credits=None, gpa=4.0)]
        self.assertEqual(summary(rows), {'credits': 2.0, 'gpa': None})
        rows.append(make_row(name='c', credits=Decimal('3.0'), gpa=3.0))
        self.assertEqual(summary(rows), {'credits': 5.0, 'gpa': 3.0})

    def test_zero_credit_rows_do_not_count(self):
        rows = [make_row(name='a', credits=Decimal('0.0'), gpa=4.0)]
        self.assertEqual(summary(rows), {'credits': 0.0, 'gpa': None})

    def test_gpa_is_rounded_to_three_decimals(self):
        rows = [make_row(name='a', credits=Decimal('1.0'), gpa=4.0),
                make_row(name='b', credits=Decimal('2.0'), gpa=3.0)]
        self.assertEqual(summary(rows), {'credits': 3.0, 'gpa': 3.333})
