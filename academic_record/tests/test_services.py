"""
Service tests: live fetch through the binding (portal mocked), store /
upsert / delete semantics and the ``GradesOut`` payload.
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from pku_account.config import PkuPortalConfig
from pku_account.extern.iaaa import PortalUnreachable
from pku_account.extern.portal import PortalClient, PortalSessionExpired
from pku_account.models import PkuPortalSession
from pku_account.services import (
    NotBound,
    PortalDisabled,
    SessionUnavailable,
    invalidate_session,
)
from academic_record import services
from academic_record.models import GradeRecord
from academic_record.parsers import parse_scores
from academic_record.tests.helpers import (
    FETCHED_AT,
    bind,
    enable_portal,
    make_person,
    make_record,
    make_row,
    make_term,
    scores_payload,
)


class ServiceTestCase(TestCase):

    def setUp(self):
        self.user, self.person = make_person()
        self.other_user, self.other_person = make_person('ar_other', '别人')
        enable_portal(self)


class FetchScoresTests(ServiceTestCase):

    def test_unbound(self):
        with patch.object(PortalClient, 'get_scores') as get_scores:
            with self.assertRaises(NotBound):
                services.fetch_scores(self.user)
        get_scores.assert_not_called()

    def test_portal_disabled(self):
        bind(self.user)
        with patch.object(PkuPortalConfig, 'enabled', False), \
                patch.object(PortalClient, 'get_scores') as get_scores:
            with self.assertRaises(PortalDisabled):
                services.fetch_scores(self.user)
        get_scores.assert_not_called()

    def test_session_unavailable(self):
        account = bind(self.user)
        invalidate_session(account, 'expired')
        with patch.object(PortalClient, 'get_scores') as get_scores:
            with self.assertRaises(SessionUnavailable):
                services.fetch_scores(self.user)
        get_scores.assert_not_called()

    def test_success_marks_session_and_sync(self):
        account = bind(self.user)
        self.assertIsNone(account.last_sync_at)
        with patch.object(PortalClient, 'get_scores',
                          return_value=scores_payload()) as get_scores:
            terms, fetched_account = services.fetch_scores(self.user)
        get_scores.assert_called_once_with()
        self.assertEqual(fetched_account.pk, account.pk)
        self.assertEqual([term.term_code for term in terms], ['25-26-1', '25-26-2'])
        self.assertIsNotNone(fetched_account.last_sync_at)
        account.refresh_from_db()
        self.assertEqual(account.last_sync_at, fetched_account.last_sync_at)
        session = PkuPortalSession.objects.get(account=account)
        self.assertFalse(session.invalid)
        # Fetching never stores anything by itself.
        self.assertFalse(GradeRecord.objects.exists())

    def test_expired_session_is_invalidated(self):
        account = bind(self.user)
        with patch.object(PortalClient, 'get_scores',
                          side_effect=PortalSessionExpired('gone')):
            with self.assertRaises(PortalSessionExpired):
                services.fetch_scores(self.user)
        session = PkuPortalSession.objects.get(account=account)
        self.assertTrue(session.invalid)
        self.assertEqual(session.invalid_reason, 'expired')
        account.refresh_from_db()
        self.assertIsNone(account.last_sync_at)
        with self.assertRaises(SessionUnavailable):
            services.fetch_scores(self.user)

    def test_unreachable_keeps_session(self):
        account = bind(self.user)
        with patch.object(PortalClient, 'get_scores',
                          side_effect=PortalUnreachable('timeout')):
            with self.assertRaises(PortalUnreachable):
                services.fetch_scores(self.user)
        session = PkuPortalSession.objects.get(account=account)
        self.assertFalse(session.invalid)
        account.refresh_from_db()
        self.assertIsNone(account.last_sync_at)

    def test_payload_without_score_list(self):
        account = bind(self.user)
        default = '门户未返回成绩数据，请稍后再试'
        cases = (
            ({'success': False, 'remark': '系统维护中'}, '系统维护中'),
            ({'success': False, 'cjxx': []}, default),
            ({}, default),
            ({'cjxx': 'x', 'msg': ' 无数据 '}, '无数据'),
            ({'success': True}, default),
        )
        for payload, message in cases:
            with self.subTest(payload=payload):
                with patch.object(PortalClient, 'get_scores', return_value=payload):
                    with self.assertRaises(services.ScoresUnavailable) as ctx:
                        services.fetch_scores(self.user)
                self.assertEqual(str(ctx.exception), message)
        account.refresh_from_db()
        self.assertIsNone(account.last_sync_at)

    def test_empty_score_list_is_a_valid_answer(self):
        account = bind(self.user)
        with patch.object(PortalClient, 'get_scores', return_value={'cjxx': []}):
            terms, _ = services.fetch_scores(self.user)
        self.assertEqual(terms, [])
        account.refresh_from_db()
        self.assertIsNotNone(account.last_sync_at)

    def test_graduate_payload(self):
        bind(self.user)
        payload = {'success': True, 'xslb': 'yjs', 'jbxx': {'xm': '研究生甲'},
                   'scoreLists': [{'kcmc': '高等量子力学', 'xf': '4', 'cj': '91',
                                   'xnd': '25-26', 'xq': '1'}]}
        with patch.object(PortalClient, 'get_scores', return_value=payload):
            terms, _ = services.fetch_scores(self.user)
        self.assertEqual([(term.term_code, [row.name for row in term.rows]) for term in terms],
                         [('25-26-1', ['高等量子力学'])])
        with patch.object(PortalClient, 'get_scores',
                          return_value={'success': True, 'xslb': 'yjs'}):
            with self.assertRaises(services.ScoresUnavailable):
                services.fetch_scores(self.user)


class StoreScoresTests(ServiceTestCase):

    def stored(self, person=None, **filters):
        return GradeRecord.objects.filter(person=person or self.person, **filters)

    def test_store_creates_rows(self):
        terms = parse_scores(scores_payload())
        count = services.store_scores(self.person, terms, FETCHED_AT)
        self.assertEqual(count, 8)
        self.assertEqual(self.stored().count(), 8)
        math = self.stored().get(course_code='00132301')
        self.assertEqual(math.term_code, '25-26-1')
        self.assertEqual(math.name, '高等数学A（一）')
        self.assertEqual(math.class_no, '01')
        self.assertEqual(math.course_type, '专业必修')
        self.assertEqual(math.credits, Decimal('5.0'))
        self.assertEqual((math.score, math.score_numeric, math.gpa), ('92', 92.0, 3.9))
        self.assertEqual(math.raw, {'bkcj': ''})
        self.assertEqual(math.fetched_at, FETCHED_AT)
        nameless = self.stored().get(course_code='00000002')
        self.assertEqual(nameless.name, '')
        english = self.stored().get(course_code='04831410')
        self.assertEqual(english.raw, {'extra': {'nested': True}})
        self.assertEqual(self.stored(term_code='25-26-2').count(), 2)

    def test_restore_is_idempotent(self):
        terms = parse_scores(scores_payload())
        services.store_scores(self.person, terms, FETCHED_AT)
        pks = set(self.stored().values_list('pk', flat=True))
        later = FETCHED_AT + timedelta(days=1)
        self.assertEqual(services.store_scores(self.person, terms, later), 8)
        self.assertEqual(set(self.stored().values_list('pk', flat=True)), pks)
        self.assertEqual(set(self.stored().values_list('fetched_at', flat=True)),
                         {later})

    def test_upsert_updates_and_removes_vanished_rows_of_that_term_only(self):
        services.store_scores(self.person, parse_scores(scores_payload()), FETCHED_AT)
        linear = self.stored().get(course_code='00132321')
        payload = scores_payload()
        term1 = payload['cjxx'][0]['list']
        term1[3]['xqcj'] = '90'
        term1[3]['jd'] = '3.7'
        del term1[1]                       # 军事理论 disappears
        terms = [term for term in parse_scores(payload) if term.term_code == '25-26-1']
        later = FETCHED_AT + timedelta(days=1)
        count = services.store_scores(self.person, terms, later)
        self.assertEqual(count, 5)
        self.assertEqual(self.stored(term_code='25-26-1').count(), 5)
        self.assertFalse(self.stored(course_code='60730020').exists())
        linear.refresh_from_db()
        self.assertEqual((linear.score, linear.score_numeric, linear.gpa),
                         ('90', 90.0, 3.7))
        self.assertEqual(linear.fetched_at, later)
        # The term that was not part of this store is untouched.
        untouched = self.stored(term_code='25-26-2')
        self.assertEqual(untouched.count(), 2)
        self.assertEqual(set(untouched.values_list('fetched_at', flat=True)),
                         {FETCHED_AT})

    def test_term_without_rows_removes_its_stored_rows(self):
        services.store_scores(self.person, parse_scores(scores_payload()), FETCHED_AT)
        count = services.store_scores(self.person, [make_term('25-26-2')], FETCHED_AT)
        self.assertEqual(count, 0)
        self.assertFalse(self.stored(term_code='25-26-2').exists())
        self.assertEqual(self.stored(term_code='25-26-1').count(), 6)

    def test_store_does_not_touch_other_persons(self):
        theirs = make_record(self.other_person, name='别人的课')
        services.store_scores(self.person, parse_scores(scores_payload()), FETCHED_AT)
        self.assertTrue(GradeRecord.objects.filter(pk=theirs.pk).exists())
        self.assertEqual(self.stored(self.other_person).count(), 1)
        services.store_scores(self.person, [make_term('25-26-1')], FETCHED_AT)
        self.assertTrue(GradeRecord.objects.filter(pk=theirs.pk).exists())

    def test_duplicate_rows_keep_the_first(self):
        term = make_term('25-26-1',
                         make_row(name='重复', score='80', score_numeric=80.0),
                         make_row(name='重复', score='95', score_numeric=95.0),
                         make_row(name='另一门', course_code='00000009'))
        count = services.store_scores(self.person, [term], FETCHED_AT)
        self.assertEqual(count, 2)
        self.assertEqual(self.stored().get(name='重复').score, '80')

    def test_store_nothing(self):
        self.assertEqual(services.store_scores(self.person, [], FETCHED_AT), 0)
        self.assertFalse(GradeRecord.objects.exists())

    def test_keys_equal_under_the_database_collation(self):
        # The unique key follows the column collation; with a
        # case-insensitive one the database, not Python, decides which
        # stored row a portal row is.
        stored = make_record(self.person, name='Course A', course_code='X1',
                             score='60', score_numeric=60.0)
        if not self.stored(pk=stored.pk, name='course a').exists():
            self.skipTest('test database collation is case-sensitive')
        term = make_term(
            '25-26-1',
            make_row(name='course a', course_code='X1', score='95',
                     score_numeric=95.0),
            make_row(name='New', course_code='X2'),
            make_row(name='new', course_code='X2', score='70',
                     score_numeric=70.0),
        )
        later = FETCHED_AT + timedelta(days=1)
        services.store_scores(self.person, [term], later)
        rows = self.stored(term_code='25-26-1')
        self.assertEqual(rows.count(), 2)
        stored.refresh_from_db()
        self.assertEqual(stored.name, 'Course A')
        self.assertEqual((stored.score, stored.fetched_at), ('95', later))
        # Two new rows the database equates collapse into one.
        self.assertEqual(rows.get(course_code='X2').score, '70')


class StoredTermsTests(ServiceTestCase):

    def test_grouping_and_order(self):
        old = make_record(self.person, term_code='24-25-1', name='旧课',
                          raw={'k': 'v'})
        first = make_record(self.person, name='甲', course_code='1')
        second = make_record(self.person, name='乙', course_code='2', credits=None)
        make_record(self.other_person, name='别人的课')
        terms = services.stored_terms(self.person)
        self.assertEqual([term.term_code for term in terms], ['25-26-1', '24-25-1'])
        self.assertEqual([row.name for row in terms[0].rows], ['甲', '乙'])
        self.assertEqual(terms[0].rows[0], make_row(name='甲', course_code='1'))
        self.assertIsNone(terms[0].rows[1].credits)
        self.assertEqual(terms[1].rows[0].raw, {'k': 'v'})
        self.assertEqual({first.pk, second.pk, old.pk},
                         set(GradeRecord.objects.filter(person=self.person)
                             .values_list('pk', flat=True)))

    def test_empty(self):
        self.assertEqual(services.stored_terms(self.person), [])
        self.assertIsNone(services.last_fetched_at(self.person))

    def test_last_fetched_at(self):
        make_record(self.person, name='a', fetched_at=FETCHED_AT)
        newest = FETCHED_AT + timedelta(hours=3)
        make_record(self.person, name='b', fetched_at=newest)
        make_record(self.other_person, name='c', fetched_at=newest + timedelta(days=9))
        self.assertEqual(services.last_fetched_at(self.person), newest)

    def test_delete_stored(self):
        make_record(self.person, name='a')
        make_record(self.person, name='b', term_code='24-25-1')
        theirs = make_record(self.other_person, name='c')
        self.assertEqual(services.delete_stored(self.person), 2)
        self.assertFalse(GradeRecord.objects.filter(person=self.person).exists())
        self.assertTrue(GradeRecord.objects.filter(pk=theirs.pk).exists())
        self.assertEqual(services.delete_stored(self.person), 0)


class GradesPayloadTests(SimpleTestCase):

    def test_shape(self):
        terms = parse_scores(scores_payload())
        payload = services.grades_payload(
            terms, stored=True, fetched_at=datetime(2026, 9, 9, 12, 0, 0))
        self.assertEqual(set(payload), {'stored', 'fetched_at', 'summary', 'terms'})
        self.assertTrue(payload['stored'])
        self.assertEqual(payload['fetched_at'], '2026-09-09T12:00:00')
        self.assertEqual(payload['summary'], {'credits': 17.0, 'gpa': 3.442})
        self.assertEqual([term['term_code'] for term in payload['terms']],
                         ['25-26-2', '25-26-1'])
        newest = payload['terms'][0]
        self.assertEqual(set(newest), {'term_code', 'summary', 'rows'})
        self.assertEqual(newest['summary'], {'credits': 2.0, 'gpa': 3.6})
        self.assertEqual(newest['rows'][0], {
            'term_code': '25-26-2', 'course_code': '04831410', 'class_no': '',
            'name': '大学英语', 'course_type': '公共必修', 'credits': 2.0,
            'score': '88.5', 'score_numeric': 88.5, 'gpa': 3.6})
        self.assertEqual(payload['terms'][1]['summary'], {'credits': 15.0, 'gpa': 3.41})
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('raw', text)
        self.assertNotIn('nested', text)
        self.assertNotIn('bkcj', text)

    def test_empty(self):
        self.assertEqual(services.grades_payload([], stored=False, fetched_at=None), {
            'stored': False, 'fetched_at': None,
            'summary': {'credits': 0.0, 'gpa': None}, 'terms': []})

    def test_input_order_does_not_matter(self):
        terms = list(reversed(parse_scores(scores_payload())))
        payload = services.grades_payload(terms, stored=False, fetched_at=None)
        self.assertEqual([term['term_code'] for term in payload['terms']],
                         ['25-26-2', '25-26-1'])
