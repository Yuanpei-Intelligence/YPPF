"""
Tests of the 北大账号 mini-program API (``/api/v2/pku/``).

``PortalClient.login`` is mocked in every test; no request leaves the
process. Passwords must never show up in logs or response bodies.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from app.models import NaturalPerson
from generic.models import User
from pku_account.config import PkuPortalConfig
from pku_account.crypto import decrypt_json
from pku_account.extern.iaaa import (
    CaptchaRequired,
    IaaaError,
    OtpRequired,
    PortalUnreachable,
)
from pku_account.extern.portal import PortalClient
from pku_account.models import PkuAccount, PkuPortalSession
from pku_account.services import login_and_bind

PASSWORD = 'S3cret-Pa55!'
PKU_ID = '2100010001'
BINDING_KEYS = {
    'bound', 'pku_username', 'verified_at', 'last_login_at', 'last_sync_at',
    'session', 'consents', 'locked_until',
}


def make_person(username: str, name: str = '测试用户') -> User:
    user = User.objects.create_user(
        username, name, User.Type.STUDENT, password='yppf-password',
    )
    NaturalPerson.objects.create(user, name=name)
    return user


def fake_client(cookies=None) -> PortalClient:
    return PortalClient.from_cookies(cookies or {'JSESSIONID': 'portal-session'})


class PkuAccountApiTestCase(APITestCase):
    def setUp(self):
        self.user = make_person('S000001')
        self.org_user = User.objects.create_user(
            'org1', 'Org One', User.Type.ORG, password='org-password',
        )
        self.special_user = User.objects.create_user(
            'special', 'Special', User.Type.SPECIAL, password='sp-password',
        )
        for name, value in (
            ('enabled', True),
            ('max_login_failures', 3),
            ('lock_seconds', 600),
            ('session_key', Fernet.generate_key().decode()),
        ):
            patcher = patch.object(PkuPortalConfig, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = APIClient()
        self.binding_url = reverse('api:pku_account:binding')
        self.login_url = reverse('api:pku_account:login')
        self.unbind_url = reverse('api:pku_account:unbind')
        self.consents_url = reverse('api:pku_account:consents')

    def bind(self, user=None, **kwargs) -> PkuAccount:
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            return login_and_bind(user or self.user, PKU_ID, PASSWORD, **kwargs)

    def post_login(self, **overrides):
        payload = {'username': PKU_ID, 'password': PASSWORD}
        payload.update(overrides)
        return self.client.post(self.login_url, payload, format='json')

    # ---- authentication / authorization -----------------------------------

    def test_endpoints_require_jwt(self):
        calls = (
            (self.client.get, self.binding_url),
            (self.client.post, self.login_url),
            (self.client.post, self.unbind_url),
            (self.client.patch, self.consents_url),
        )
        for method, url in calls:
            with self.subTest(url=url):
                response = method(url, {}, format='json')
                self.assertEqual(response.status_code,
                                 status.HTTP_401_UNAUTHORIZED)

    def test_malformed_jwt_is_401(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer not-a-token')
        response = self.client.get(self.binding_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_real_jwt_is_accepted(self):
        token = str(AccessToken.for_user(self.user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.get(self.binding_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()['bound'])

    def test_org_user_is_forbidden(self):
        self.client.force_authenticate(self.org_user)
        calls = (
            (self.client.get, self.binding_url),
            (self.client.post, self.login_url),
            (self.client.post, self.unbind_url),
            (self.client.patch, self.consents_url),
        )
        for method, url in calls:
            with self.subTest(url=url):
                response = method(
                    url, {'username': PKU_ID, 'password': PASSWORD},
                    format='json',
                )
                self.assertEqual(response.status_code,
                                 status.HTTP_403_FORBIDDEN)
                body = response.json()
                self.assertEqual(body['code'], 'PERSON_REQUIRED')
                self.assertIn('message', body)
        self.assertFalse(PkuAccount.objects.exists())

    def test_special_user_is_forbidden(self):
        self.client.force_authenticate(self.special_user)
        response = self.client.get(self.binding_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- GET binding/ -----------------------------------------------------

    def test_binding_unbound(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.binding_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(set(body), BINDING_KEYS)
        self.assertFalse(body['bound'])
        self.assertIsNone(body['pku_username'])
        self.assertEqual(body['session'],
                         {'alive': None, 'last_ok_at': None,
                          'invalid_reason': ''})
        self.assertEqual(body['consents'],
                         {'timetable': False, 'grades': False})

    def test_binding_bound_shows_own_binding_only(self):
        other = make_person('S000002', name='其他人')
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            login_and_bind(other, '2100010002', PASSWORD, consent_grades=True)
        self.bind(consent_timetable=True)

        self.client.force_authenticate(self.user)
        body = self.client.get(self.binding_url).json()
        self.assertTrue(body['bound'])
        self.assertEqual(body['pku_username'], PKU_ID)
        self.assertEqual(body['consents'],
                         {'timetable': True, 'grades': False})
        self.assertTrue(body['session']['alive'])
        self.assertIsNone(body['locked_until'])

    # ---- POST login/ ------------------------------------------------------

    def test_login_happy_path(self):
        self.client.force_authenticate(self.user)
        with patch.object(
            PortalClient, 'login', return_value=fake_client(),
        ) as login:
            response = self.post_login(consent_timetable=True)
        login.assert_called_once_with(PKU_ID, PASSWORD)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(set(body), BINDING_KEYS)
        self.assertTrue(body['bound'])
        self.assertEqual(body['pku_username'], PKU_ID)
        self.assertTrue(body['consents']['timetable'])
        self.assertFalse(body['consents']['grades'])
        self.assertTrue(body['session']['alive'])
        self.assertNotIn(PASSWORD, response.content.decode())

        account = PkuAccount.objects.get(user=self.user)
        session = PkuPortalSession.objects.get(account=account)
        self.assertNotIn(b'portal-session', bytes(session.cookies_encrypted))
        self.assertEqual(decrypt_json(session.cookies_encrypted),
                         [{'name': 'JSESSIONID', 'value': 'portal-session', 'path': '/'}])

    def test_login_relogin_updates_same_binding(self):
        first = self.bind()
        self.client.force_authenticate(self.user)
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            response = self.post_login(consent_grades=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(PkuAccount.objects.count(), 1)
        self.assertEqual(PkuAccount.objects.get().pk, first.pk)
        self.assertTrue(response.json()['consents']['grades'])

    def test_login_invalid_input(self):
        self.client.force_authenticate(self.user)
        with patch.object(PortalClient, 'login') as login:
            response = self.client.post(
                self.login_url, {'username': PKU_ID}, format='json',
            )
        login.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertEqual(body['code'], 'INVALID_INPUT')
        self.assertIn('message', body)
        self.assertFalse(PkuAccount.objects.exists())

    def test_login_iaaa_error(self):
        self.client.force_authenticate(self.user)
        with patch.object(
            PortalClient, 'login',
            side_effect=IaaaError('E01', '用户名或密码错误'),
        ):
            response = self.post_login()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(),
                         {'code': 'IAAA_ERROR', 'message': '用户名或密码错误'})
        self.assertFalse(PkuAccount.objects.exists())

    def test_login_otp_and_captcha(self):
        self.client.force_authenticate(self.user)
        cases = (
            (OtpRequired('E03', '需要二次验证'), 'OTP_REQUIRED'),
            (CaptchaRequired('E02', '请输入验证码'), 'CAPTCHA_REQUIRED'),
        )
        for error, code in cases:
            with self.subTest(code=code):
                with patch.object(PortalClient, 'login', side_effect=error):
                    response = self.post_login()
                self.assertEqual(response.status_code,
                                 status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json(),
                                 {'code': code, 'message': error.msg})

    def test_login_locked(self):
        account = self.bind()
        PkuAccount.objects.filter(pk=account.pk).update(
            login_failures=3,
            locked_until=datetime.now() + timedelta(minutes=5),
        )
        self.client.force_authenticate(self.user)
        with patch.object(PortalClient, 'login') as login:
            response = self.post_login()
        login.assert_not_called()
        self.assertEqual(response.status_code,
                         status.HTTP_429_TOO_MANY_REQUESTS)
        body = response.json()
        self.assertEqual(body['code'], 'LOCKED')
        self.assertIn('message', body)
        binding = self.client.get(self.binding_url).json()
        self.assertIsNotNone(binding['locked_until'])

    def test_login_failures_lock_through_the_api(self):
        self.bind()
        self.client.force_authenticate(self.user)
        with patch.object(
            PortalClient, 'login',
            side_effect=IaaaError('E01', '用户名或密码错误'),
        ):
            for _ in range(3):
                self.assertEqual(self.post_login().status_code,
                                 status.HTTP_400_BAD_REQUEST)
            response = self.post_login()
        self.assertEqual(response.status_code,
                         status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()['code'], 'LOCKED')

    def test_login_already_bound_elsewhere(self):
        other = make_person('S000002', name='其他人')
        self.bind(user=other)
        self.client.force_authenticate(self.user)
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            response = self.post_login()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        body = response.json()
        self.assertEqual(body['code'], 'ALREADY_BOUND_ELSEWHERE')
        self.assertIn('message', body)
        self.assertFalse(PkuAccount.objects.filter(user=self.user).exists())

    def test_login_portal_disabled(self):
        self.client.force_authenticate(self.user)
        with patch.object(PkuPortalConfig, 'enabled', False), \
                patch.object(PortalClient, 'login') as login:
            response = self.post_login()
        login.assert_not_called()
        self.assertEqual(response.status_code,
                         status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body['code'], 'PORTAL_DISABLED')
        self.assertIn('message', body)

    def test_login_portal_unreachable(self):
        self.client.force_authenticate(self.user)
        with patch.object(
            PortalClient, 'login',
            side_effect=PortalUnreachable('无法连接北京大学信息门户'),
        ):
            response = self.post_login()
        self.assertEqual(response.status_code,
                         status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()['code'], 'PORTAL_UNREACHABLE')

    # ---- POST unbind/ -----------------------------------------------------

    def test_unbind(self):
        self.bind()
        self.client.force_authenticate(self.user)
        response = self.client.post(self.unbind_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PkuAccount.objects.exists())
        self.assertFalse(PkuPortalSession.objects.exists())
        self.assertFalse(self.client.get(self.binding_url).json()['bound'])
        # Unbinding again is a harmless no-op.
        response = self.client.post(self.unbind_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_unbind_does_not_touch_other_users(self):
        other = make_person('S000002', name='其他人')
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            login_and_bind(other, '2100010002', PASSWORD)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(self.unbind_url).status_code,
                         status.HTTP_204_NO_CONTENT)
        self.assertTrue(PkuAccount.objects.filter(user=other).exists())

    # ---- PATCH consents/ --------------------------------------------------

    def test_consents_patch(self):
        self.bind()
        self.client.force_authenticate(self.user)
        response = self.client.patch(
            self.consents_url, {'timetable': True}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(set(body), BINDING_KEYS)
        self.assertEqual(body['consents'],
                         {'timetable': True, 'grades': False})

        response = self.client.patch(
            self.consents_url, {'grades': True, 'timetable': False},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['consents'],
                         {'timetable': False, 'grades': True})
        account = PkuAccount.objects.get(user=self.user)
        self.assertFalse(account.consent_timetable)
        self.assertTrue(account.consent_grades)

    def test_consents_patch_rejects_empty_and_invalid_bodies(self):
        self.bind()
        self.client.force_authenticate(self.user)
        for payload in ({}, {'timetable': 'maybe'}):
            with self.subTest(payload=payload):
                response = self.client.patch(
                    self.consents_url, payload, format='json',
                )
                self.assertEqual(response.status_code,
                                 status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json()['code'], 'INVALID_INPUT')

    def test_consents_patch_requires_binding(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(
            self.consents_url, {'timetable': True}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        body = response.json()
        self.assertEqual(body['code'], 'NOT_BOUND')
        self.assertIn('message', body)

    # ---- secrets ----------------------------------------------------------

    def test_password_never_appears_in_logs_or_responses(self):
        self.client.force_authenticate(self.user)
        bodies = []
        with self.assertLogs(level='DEBUG') as logs:
            with patch.object(
                PortalClient, 'login',
                side_effect=IaaaError('E01', '用户名或密码错误'),
            ):
                bodies.append(self.post_login().content.decode())
            with patch.object(
                PortalClient, 'login', return_value=fake_client(),
            ):
                bodies.append(
                    self.post_login(consent_timetable=True).content.decode())
            bodies.append(self.client.post(
                self.login_url, {'password': PASSWORD}, format='json',
            ).content.decode())
            bodies.append(self.client.get(self.binding_url).content.decode())

        joined_logs = '\n'.join(logs.output)
        self.assertNotIn(PASSWORD, joined_logs)
        for body in bodies:
            self.assertNotIn(PASSWORD, body)
