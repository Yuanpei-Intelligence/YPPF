"""
Tests of the grades mini-program API (``/api/v2/grades/``).

The portal is mocked at ``PortalClient.get_scores`` (or the ``pku_account``
services are patched); nothing reaches pku.edu.cn. Bindings are real rows
created through ``pku_account.services.login_and_bind`` with a mocked IAAA
login. ``raw`` must never appear in a response and score payloads must
never be logged.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from generic.models import User
from pku_account.config import PkuPortalConfig
from pku_account.extern.iaaa import PortalUnreachable
from pku_account.extern.portal import PortalClient, PortalSessionExpired
from pku_account.models import PkuAccount, PkuPortalSession
from pku_account.services import SessionUnavailable, invalidate_session
from academic_record.models import GradeRecord
from academic_record.tests.helpers import (
    FETCHED_AT,
    bind,
    enable_portal,
    make_person,
    make_record,
    scores_payload,
)

GRADES_OUT_KEYS = {'stored', 'fetched_at', 'summary', 'terms'}
ROW_KEYS = {
    'term_code', 'course_code', 'class_no', 'name', 'course_type', 'credits',
    'score', 'score_numeric', 'gpa',
}
RAW_SENTINEL = 'RAW-SENTINEL-VALUE'


def sentinel_payload() -> dict:
    payload = scores_payload()
    payload['cjxx'][0]['list'][0]['bkcj'] = RAW_SENTINEL
    return payload


def assert_json_numbers(testcase, body: dict) -> None:
    """
    Every ``credits`` / ``gpa`` / ``score_numeric`` of a rendered
    ``GradesOut`` body is a JSON number (or null where allowed), never a
    Decimal rendered as a string.
    """
    def check(value, allow_null):
        if value is None and allow_null:
            return
        testcase.assertIsInstance(value, (int, float))
        testcase.assertNotIsInstance(value, bool)

    check(body['summary']['credits'], False)
    check(body['summary']['gpa'], True)
    for term in body['terms']:
        check(term['summary']['credits'], False)
        check(term['summary']['gpa'], True)
        for row in term['rows']:
            check(row['credits'], True)
            check(row['score_numeric'], True)
            check(row['gpa'], True)


class GradesAPITestCase(APITestCase):

    def setUp(self):
        enable_portal(self)
        self.client = APIClient()
        self.user, self.person = make_person('ar_api_student', 'API 同学')
        self.other_user, self.other_person = make_person('ar_api_other', '别的同学')
        self.org_user = User.objects.create_user(
            'ar_api_org', '某小组', User.Type.ORG, password='pw')
        self.grades_url = reverse('api:academic_record:grades')
        self.sync_url = reverse('api:academic_record:sync')
        self.client.force_authenticate(user=self.user)

    def sync(self, payload=None, **patch_kwargs):
        if payload is not None:
            patch_kwargs['return_value'] = payload
        with patch.object(PortalClient, 'get_scores', **patch_kwargs):
            return self.client.post(self.sync_url)

    def mine(self):
        return GradeRecord.objects.filter(person=self.person)


class AuthTests(GradesAPITestCase):

    def endpoints(self):
        return [
            ('get', self.grades_url),
            ('delete', self.grades_url),
            ('post', self.sync_url),
        ]

    def test_anonymous_gets_401(self):
        self.client.force_authenticate(user=None)
        for method, url in self.endpoints():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(response.data['code'], 'not_authenticated')
                self.assertIn('message', response.data)

    def test_malformed_jwt_gets_401(self):
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer not-a-token')
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['code'], 'invalid_token')

    def test_real_jwt_is_accepted(self):
        bind(self.user, consent_grades=True)
        self.client.force_authenticate(user=None)
        token = str(AccessToken.for_user(self.user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['terms'], [])

    def test_organization_gets_403(self):
        self.client.force_authenticate(user=self.org_user)
        for method, url in self.endpoints():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.data['code'], 'permission_denied')
                self.assertIn('message', response.data)

    def test_person_without_profile_gets_403(self):
        orphan = User.objects.create_user('ar_api_orphan', '无档案', User.Type.STUDENT,
                                          password='pw')
        self.client.force_authenticate(user=orphan)
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'permission_denied')

    def test_get_is_safe_and_sync_needs_post(self):
        self.assertEqual(self.client.get(self.sync_url).status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.post(self.grades_url).status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)


class GetGradesTests(GradesAPITestCase):

    def test_unbound(self):
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'NOT_BOUND')
        self.assertIn('message', response.data)

    def test_consent_required(self):
        bind(self.user)
        make_record(self.person, name='偷偷存的')
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'CONSENT_REQUIRED')
        self.assertNotIn('偷偷存的', response.content.decode())

    def test_nothing_stored(self):
        bind(self.user, consent_grades=True)
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'stored': False, 'fetched_at': None,
            'summary': {'credits': 0.0, 'gpa': None}, 'terms': []})

    def test_stored_rows_of_the_caller_only(self):
        bind(self.user, consent_grades=True)
        make_record(self.person, name='旧课', term_code='24-25-1', raw={'x': RAW_SENTINEL})
        make_record(self.person, name='新课', course_code='2', credits=None, gpa=None,
                    score='P', score_numeric=None,
                    fetched_at=FETCHED_AT + timedelta(hours=1))
        make_record(self.other_person, name='别人的课')
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(set(data), GRADES_OUT_KEYS)
        self.assertTrue(data['stored'])
        self.assertEqual(data['fetched_at'], '2026-09-09T13:00:00')
        self.assertEqual(data['summary'], {'credits': 2.0, 'gpa': 3.4})
        self.assertEqual([term['term_code'] for term in data['terms']],
                         ['25-26-1', '24-25-1'])
        self.assertEqual(data['terms'][0]['summary'], {'credits': 0.0, 'gpa': None})
        row = data['terms'][0]['rows'][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row['name'], '新课')
        self.assertIsNone(row['credits'])
        self.assertEqual(row['score'], 'P')
        self.assertEqual(data['terms'][1]['rows'][0]['credits'], 2.0)
        assert_json_numbers(self, response.json())
        body = response.content.decode()
        self.assertNotIn('别人的课', body)
        self.assertNotIn(RAW_SENTINEL, body)
        self.assertNotIn('"raw"', body)

    def test_credits_are_json_numbers(self):
        bind(self.user, consent_grades=True)
        make_record(self.person, name='半学分课', credits=Decimal('0.5'), gpa=4.0)
        make_record(self.person, name='三学分课', course_code='3', credits=Decimal('3'),
                    gpa=3.0)
        body = self.client.get(self.grades_url).json()
        assert_json_numbers(self, body)
        rows = {row['name']: row for row in body['terms'][0]['rows']}
        self.assertEqual(rows['半学分课']['credits'], 0.5)
        self.assertEqual(rows['三学分课']['credits'], 3.0)
        self.assertEqual(body['summary'], {'credits': 3.5, 'gpa': 3.143})
        self.assertEqual(body['terms'][0]['summary'], body['summary'])
        rendered = self.client.get(self.grades_url).content.decode()
        self.assertNotIn('"credits": "', rendered)
        self.assertNotIn('"credits":"', rendered)


class SyncTests(GradesAPITestCase):

    def test_unbound(self):
        with patch.object(PortalClient, 'get_scores') as get_scores:
            response = self.client.post(self.sync_url)
        get_scores.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'NOT_BOUND')

    def test_session_unavailable(self):
        account = bind(self.user)
        invalidate_session(account, 'expired')
        response = self.sync(scores_payload())
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')
        self.assertIn('message', response.data)

    def test_session_unavailable_from_patched_service(self):
        bind(self.user)
        with patch('academic_record.services.get_client',
                   side_effect=SessionUnavailable('gone')):
            response = self.client.post(self.sync_url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')

    def test_session_expired_is_invalidated(self):
        account = bind(self.user, consent_grades=True)
        response = self.sync(side_effect=PortalSessionExpired('gone'))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'PKU_LOGIN_REQUIRED')
        session = PkuPortalSession.objects.get(account=account)
        self.assertTrue(session.invalid)
        self.assertEqual(session.invalid_reason, 'expired')
        self.assertFalse(self.mine().exists())
        account.refresh_from_db()
        self.assertIsNone(account.last_sync_at)

    def test_portal_unreachable(self):
        bind(self.user)
        response = self.sync(side_effect=PortalUnreachable('无法连接北京大学信息门户'))
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data, {'code': 'PORTAL_UNREACHABLE',
                                         'message': '无法连接北京大学信息门户'})

    def test_portal_disabled(self):
        bind(self.user)
        with patch.object(PkuPortalConfig, 'enabled', False):
            response = self.sync(scores_payload())
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['code'], 'PORTAL_DISABLED')
        self.assertIn('message', response.data)

    def test_payload_without_scores(self):
        account = bind(self.user, consent_grades=True)
        response = self.sync({'success': False, 'remark': '系统维护中'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {'code': 'PARSE_FAILED', 'message': '系统维护中'})
        self.assertFalse(self.mine().exists())
        account.refresh_from_db()
        self.assertIsNone(account.last_sync_at)

    def test_sync_without_consent_shows_but_does_not_store(self):
        account = bind(self.user)
        with self.assertNoLogs('academic_record', level='DEBUG'), \
                self.assertNoLogs('api.academic_record', level='DEBUG'):
            response = self.sync(sentinel_payload())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data
        self.assertEqual(set(data), GRADES_OUT_KEYS)
        self.assertFalse(data['stored'])
        self.assertEqual(data['summary'], {'credits': 17.0, 'gpa': 3.442})
        self.assertEqual([term['term_code'] for term in data['terms']],
                         ['25-26-2', '25-26-1'])
        self.assertEqual(len(data['terms'][1]['rows']), 6)
        self.assertEqual(set(data['terms'][1]['rows'][0]), ROW_KEYS)
        assert_json_numbers(self, response.json())
        self.assertFalse(GradeRecord.objects.exists())
        account.refresh_from_db()
        self.assertIsNotNone(account.last_sync_at)
        self.assertEqual(data['fetched_at'],
                         account.last_sync_at.strftime('%Y-%m-%dT%H:%M:%S'))
        body = response.content.decode()
        self.assertNotIn(RAW_SENTINEL, body)
        self.assertNotIn('"raw"', body)

    def test_sync_with_consent_stores(self):
        account = bind(self.user, consent_grades=True)
        make_record(self.other_person, name='别人的课')
        response = self.sync(sentinel_payload())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['stored'])
        self.assertEqual(self.mine().count(), 8)
        account.refresh_from_db()
        self.assertEqual(set(self.mine().values_list('fetched_at', flat=True)),
                         {account.last_sync_at})
        self.assertEqual(response.data['fetched_at'],
                         account.last_sync_at.strftime('%Y-%m-%dT%H:%M:%S'))
        math = self.mine().get(course_code='00132301')
        self.assertEqual(math.raw, {'bkcj': RAW_SENTINEL})
        self.assertNotIn(RAW_SENTINEL, response.content.decode())
        self.assertEqual(GradeRecord.objects.filter(person=self.other_person).count(), 1)

        # GET now serves the stored rows.
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['stored'])
        self.assertEqual(response.data['summary'], {'credits': 17.0, 'gpa': 3.442})
        assert_json_numbers(self, response.json())
        self.assertNotIn(RAW_SENTINEL, response.content.decode())

        # A second sync with fewer rows replaces the term's rows.
        payload = scores_payload()
        del payload['cjxx'][0]['list'][1]
        response = self.sync(payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['stored'])
        self.assertEqual(self.mine().count(), 7)
        self.assertFalse(self.mine().filter(course_code='60730020').exists())

    def test_sync_with_consent_but_empty_list_is_not_stored(self):
        bind(self.user, consent_grades=True)
        response = self.sync({'cjxx': []})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['stored'])
        self.assertEqual(response.data['terms'], [])
        self.assertIsNotNone(response.data['fetched_at'])


class DeleteAndConsentTests(GradesAPITestCase):

    def test_delete_wipes_own_rows(self):
        bind(self.user, consent_grades=True)
        make_record(self.person, name='a')
        make_record(self.person, name='b', term_code='24-25-1')
        theirs = make_record(self.other_person, name='c')
        response = self.client.delete(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(self.mine().exists())
        self.assertTrue(GradeRecord.objects.filter(pk=theirs.pk).exists())
        # Consent is untouched; GET simply has nothing to show.
        self.assertTrue(PkuAccount.objects.get(user=self.user).consent_grades)
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['stored'])

    def test_delete_without_binding_or_rows(self):
        response = self.client.delete(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_revoking_consent_through_the_pku_api_deletes_rows(self):
        bind(self.user, consent_grades=True)
        make_record(self.person, name='a')
        theirs = make_record(self.other_person, name='c')
        consents_url = reverse('api:pku_account:consents')
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(consents_url, {'grades': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.mine().exists())
        self.assertTrue(GradeRecord.objects.filter(pk=theirs.pk).exists())
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'CONSENT_REQUIRED')

    def test_unbinding_through_the_pku_api_deletes_rows(self):
        bind(self.user, consent_grades=True)
        make_record(self.person, name='a')
        response = self.client.post(reverse('api:pku_account:unbind'))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(self.mine().exists())
        response = self.client.get(self.grades_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'NOT_BOUND')
