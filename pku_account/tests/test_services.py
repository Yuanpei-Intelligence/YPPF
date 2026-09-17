"""
Tests of ``pku_account.services``. ``PortalClient.login`` is mocked so no
HTTP is performed; everything else (models, crypto) is real.
"""
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import TestCase

from app.models import NaturalPerson
from generic.models import User
from pku_account import services
from pku_account.config import PkuPortalConfig
from pku_account.crypto import decrypt_json
from pku_account.extern.iaaa import CaptchaRequired, IaaaError, OtpRequired
from pku_account.extern.portal import PortalClient
from pku_account.models import PkuAccount, PkuPortalSession

PASSWORD = 'S3cret-Pa55!'
PKU_ID = '2100010001'
ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')


def make_person(username: str, name: str = '测试用户') -> User:
    user = User.objects.create_user(
        username, name, User.Type.STUDENT, password='yppf-password',
    )
    NaturalPerson.objects.create(user, name=name)
    return user


def fake_client(cookies=None) -> PortalClient:
    return PortalClient.from_cookies(cookies or {'JSESSIONID': 'portal-session'})


def wrong_password() -> IaaaError:
    return IaaaError('E01', '用户名或密码错误')


class ServiceTestCase(TestCase):
    """Common fixtures: a person, portal enabled, a known Fernet key."""

    def setUp(self):
        self.user = make_person('S000001')
        for name, value in (
            ('enabled', True),
            ('max_login_failures', 3),
            ('lock_seconds', 600),
            ('session_key', Fernet.generate_key().decode()),
        ):
            patcher = patch.object(PkuPortalConfig, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def bind(self, user=None, cookies=None, **kwargs) -> PkuAccount:
        with patch.object(
            PortalClient, 'login', return_value=fake_client(cookies),
        ):
            return services.login_and_bind(
                user or self.user, PKU_ID, PASSWORD, **kwargs,
            )


class LoginAndBindTests(ServiceTestCase):
    def test_new_binding_stores_encrypted_session(self):
        with patch.object(
            PortalClient, 'login', return_value=fake_client(),
        ) as login:
            account = services.login_and_bind(
                self.user, PKU_ID, PASSWORD, consent_timetable=True,
            )
        login.assert_called_once_with(PKU_ID, PASSWORD)

        account.refresh_from_db()
        self.assertEqual(account.user, self.user)
        self.assertEqual(account.pku_username, PKU_ID)
        self.assertIsNotNone(account.verified_at)
        self.assertIsNotNone(account.last_login_at)
        self.assertIsNone(account.last_sync_at)
        self.assertEqual(account.login_failures, 0)
        self.assertIsNone(account.locked_until)
        self.assertTrue(account.consent_timetable)
        self.assertIsNotNone(account.consent_timetable_at)
        self.assertFalse(account.consent_grades)
        self.assertIsNone(account.consent_grades_at)

        session = PkuPortalSession.objects.get(account=account)
        stored = bytes(session.cookies_encrypted)
        self.assertNotIn(b'portal-session', stored)
        # Stored with paths: publicQuery sets JSESSIONID at "/" and "/publicQuery".
        self.assertEqual(decrypt_json(stored),
                         [{'name': 'JSESSIONID', 'value': 'portal-session', 'path': '/'}])
        self.assertFalse(session.invalid)
        self.assertEqual(session.invalid_reason, '')
        self.assertIsNotNone(session.last_ok_at)
        self.assertIsNotNone(session.last_checked_at)

    def test_username_is_stripped_and_password_is_not_stored(self):
        with patch.object(PortalClient, 'login', return_value=fake_client()) \
                as login:
            services.login_and_bind(self.user, f'  {PKU_ID} ', PASSWORD)
        login.assert_called_once_with(PKU_ID, PASSWORD)
        account = PkuAccount.objects.get(user=self.user)
        self.assertEqual(account.pku_username, PKU_ID)
        # Nothing in either table may contain the password, encrypted or not.
        session = PkuPortalSession.objects.get(account=account)
        self.assertNotIn(PASSWORD, str(decrypt_json(session.cookies_encrypted)))

    def test_relogin_replaces_session_and_keeps_verified_at(self):
        first_time = datetime(2026, 9, 1, 8, 0, 0)
        with patch('pku_account.services.datetime') as mocked:
            mocked.now.return_value = first_time
            account = self.bind(cookies={'JSESSIONID': 'old'})
        account.login_failures = 2
        account.save(update_fields=['login_failures'])
        services.invalidate_session(account, 'expired')

        second_time = datetime(2026, 9, 9, 12, 0, 0)
        with patch('pku_account.services.datetime') as mocked:
            mocked.now.return_value = second_time
            again = self.bind(cookies={'JSESSIONID': 'new'},
                              consent_grades=True)

        self.assertEqual(again.pk, account.pk)
        again.refresh_from_db()
        self.assertEqual(again.verified_at, first_time)
        self.assertEqual(again.last_login_at, second_time)
        self.assertEqual(again.login_failures, 0)
        self.assertTrue(again.consent_grades)
        self.assertEqual(again.consent_grades_at, second_time)
        self.assertEqual(PkuPortalSession.objects.count(), 1)
        session = PkuPortalSession.objects.get(account=again)
        self.assertEqual(decrypt_json(session.cookies_encrypted),
                         [{'name': 'JSESSIONID', 'value': 'new', 'path': '/'}])
        self.assertFalse(session.invalid)
        self.assertEqual(session.invalid_reason, '')
        self.assertEqual(session.last_ok_at, second_time)

    def test_consent_none_leaves_flags_unchanged(self):
        self.bind(consent_timetable=True, consent_grades=True)
        account = self.bind()
        account.refresh_from_db()
        self.assertTrue(account.consent_timetable)
        self.assertTrue(account.consent_grades)

    def test_already_bound_to_another_user(self):
        other = make_person('S000002', name='其他人')
        self.bind(user=other)
        with self.assertRaises(services.AlreadyBoundElsewhere):
            self.bind()
        self.assertFalse(PkuAccount.objects.filter(user=self.user).exists())
        self.assertEqual(PkuAccount.objects.get(pku_username=PKU_ID).user, other)

    def test_disabled_portal_rejects_before_any_network(self):
        with patch.object(PkuPortalConfig, 'enabled', False), \
                patch.object(PortalClient, 'login') as login:
            with self.assertRaises(services.PortalDisabled):
                services.login_and_bind(self.user, PKU_ID, PASSWORD)
        login.assert_not_called()

    def test_wrong_password_counts_and_locks_existing_binding(self):
        self.bind()
        now = datetime(2026, 9, 9, 12, 0, 0)
        with patch('pku_account.services.datetime') as mocked, \
                patch.object(PortalClient, 'login',
                             side_effect=wrong_password()) as login:
            mocked.now.return_value = now
            for expected in (1, 2):
                with self.assertRaises(IaaaError):
                    services.login_and_bind(self.user, PKU_ID, PASSWORD)
                account = PkuAccount.objects.get(user=self.user)
                self.assertEqual(account.login_failures, expected)
                self.assertIsNone(account.locked_until)
            with self.assertRaises(IaaaError):
                services.login_and_bind(self.user, PKU_ID, PASSWORD)
            account = PkuAccount.objects.get(user=self.user)
            self.assertEqual(account.login_failures, 3)
            self.assertEqual(account.locked_until, now + timedelta(seconds=600))
            self.assertEqual(login.call_count, 3)

            # Locked: refused before touching IAAA.
            with self.assertRaises(services.AccountLocked) as ctx:
                services.login_and_bind(self.user, PKU_ID, PASSWORD)
            self.assertEqual(ctx.exception.locked_until, account.locked_until)
            self.assertEqual(login.call_count, 3)

        # After the lock expired a correct login clears everything.
        later = now + timedelta(seconds=601)
        with patch('pku_account.services.datetime') as mocked:
            mocked.now.return_value = later
            account = self.bind()
        account.refresh_from_db()
        self.assertEqual(account.login_failures, 0)
        self.assertIsNone(account.locked_until)

    def test_failure_after_expired_lock_starts_new_window(self):
        account = self.bind()
        past = datetime.now() - timedelta(seconds=1)
        PkuAccount.objects.filter(pk=account.pk).update(
            login_failures=3, locked_until=past,
        )
        with patch.object(PortalClient, 'login', side_effect=wrong_password()):
            with self.assertRaises(IaaaError):
                services.login_and_bind(self.user, PKU_ID, PASSWORD)
        account.refresh_from_db()
        self.assertEqual(account.login_failures, 1)
        self.assertIsNone(account.locked_until)

    def test_wrong_password_without_binding_is_not_recorded(self):
        with patch.object(PortalClient, 'login', side_effect=wrong_password()):
            with self.assertRaises(IaaaError):
                services.login_and_bind(self.user, PKU_ID, PASSWORD)
        self.assertFalse(PkuAccount.objects.exists())
        self.assertFalse(PkuPortalSession.objects.exists())

    def test_captcha_and_otp_are_not_counted_as_failures(self):
        self.bind()
        for error in (CaptchaRequired('E02', '请输入验证码'),
                      OtpRequired('E03', '需要二次验证')):
            with self.subTest(error=type(error).__name__):
                with patch.object(PortalClient, 'login', side_effect=error):
                    with self.assertRaises(type(error)):
                        services.login_and_bind(self.user, PKU_ID, PASSWORD)
                account = PkuAccount.objects.get(user=self.user)
                self.assertEqual(account.login_failures, 0)
                self.assertIsNone(account.locked_until)


class SessionTests(ServiceTestCase):
    def test_get_client_restores_cookies(self):
        self.bind(cookies={'JSESSIONID': 'abc', 'route': 'r1'})
        client = services.get_client(self.user)
        self.assertEqual(client.cookies(), {'JSESSIONID': 'abc', 'route': 'r1'})

    def test_get_client_without_binding(self):
        with self.assertRaises(services.SessionUnavailable):
            services.get_client(self.user)

    def test_get_client_without_session_row(self):
        account = self.bind()
        PkuPortalSession.objects.filter(account=account).delete()
        with self.assertRaises(services.SessionUnavailable):
            services.get_client(self.user)

    def test_get_client_on_invalid_session(self):
        account = self.bind()
        services.invalidate_session(account, 'expired')
        session = PkuPortalSession.objects.get(account=account)
        self.assertTrue(session.invalid)
        self.assertEqual(session.invalid_reason, 'expired')
        self.assertIsNotNone(session.last_checked_at)
        with self.assertRaises(services.SessionUnavailable):
            services.get_client(self.user)

    def test_get_client_marks_undecryptable_session_invalid(self):
        account = self.bind()
        PkuPortalSession.objects.filter(account=account).update(
            cookies_encrypted=Fernet(Fernet.generate_key()).encrypt(b'{}'),
        )
        with self.assertRaises(services.SessionUnavailable):
            services.get_client(self.user)
        session = PkuPortalSession.objects.get(account=account)
        self.assertTrue(session.invalid)
        self.assertEqual(session.invalid_reason, 'key_changed')

    def test_invalidate_reason_is_truncated_and_noop_without_session(self):
        account = self.bind()
        services.invalidate_session(account, 'x' * 100)
        session = PkuPortalSession.objects.get(account=account)
        self.assertEqual(len(session.invalid_reason), 64)
        PkuPortalSession.objects.filter(account=account).delete()
        services.invalidate_session(account, 'again')  # must not raise

    def test_mark_session_ok(self):
        account = self.bind()
        services.invalidate_session(account, 'expired')
        self.assertIsNone(account.last_sync_at)

        services.mark_session_ok(account, synced=False)
        session = PkuPortalSession.objects.get(account=account)
        self.assertFalse(session.invalid)
        self.assertEqual(session.invalid_reason, '')
        self.assertIsNotNone(session.last_ok_at)
        account.refresh_from_db()
        self.assertIsNone(account.last_sync_at)

        services.mark_session_ok(account)
        account.refresh_from_db()
        self.assertIsNotNone(account.last_sync_at)


class ConsentAndUnbindTests(ServiceTestCase):
    def test_update_consents(self):
        self.bind()
        account = services.update_consents(self.user, timetable=True)
        account.refresh_from_db()
        self.assertTrue(account.consent_timetable)
        self.assertIsNotNone(account.consent_timetable_at)
        self.assertFalse(account.consent_grades)
        self.assertIsNone(account.consent_grades_at)

        account = services.update_consents(self.user, grades=True,
                                           timetable=False)
        account.refresh_from_db()
        self.assertFalse(account.consent_timetable)
        self.assertTrue(account.consent_grades)
        self.assertIsNotNone(account.consent_grades_at)

    def test_update_consents_requires_binding(self):
        with self.assertRaises(services.NotBound):
            services.update_consents(self.user, timetable=True)

    def test_unbind_removes_binding_and_session(self):
        self.bind()
        services.unbind(self.user)
        self.assertFalse(PkuAccount.objects.exists())
        self.assertFalse(PkuPortalSession.objects.exists())
        services.unbind(self.user)  # idempotent
        self.assertIsNone(services.get_binding(self.user))

    def test_unbind_only_affects_the_caller(self):
        other = make_person('S000002', name='其他人')
        self.bind()
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            services.login_and_bind(other, '2100010002', PASSWORD)
        services.unbind(self.user)
        self.assertTrue(PkuAccount.objects.filter(user=other).exists())


class BindingPayloadTests(ServiceTestCase):
    def test_unbound_payload(self):
        self.assertEqual(services.binding_payload(None), {
            'bound': False,
            'pku_username': None,
            'verified_at': None,
            'last_login_at': None,
            'last_sync_at': None,
            'session': {'alive': None, 'last_ok_at': None,
                        'invalid_reason': ''},
            'consents': {'timetable': False, 'grades': False},
            'locked_until': None,
        })

    def test_bound_payload(self):
        account = self.bind(consent_timetable=True)
        payload = services.binding_payload(services.get_binding(self.user))
        self.assertTrue(payload['bound'])
        self.assertEqual(payload['pku_username'], PKU_ID)
        self.assertRegex(payload['verified_at'], ISO_RE)
        self.assertRegex(payload['last_login_at'], ISO_RE)
        self.assertIsNone(payload['last_sync_at'])
        self.assertEqual(payload['session']['alive'], True)
        self.assertRegex(payload['session']['last_ok_at'], ISO_RE)
        self.assertEqual(payload['session']['invalid_reason'], '')
        self.assertEqual(payload['consents'],
                         {'timetable': True, 'grades': False})
        self.assertIsNone(payload['locked_until'])

        services.invalidate_session(account, 'expired')
        payload = services.binding_payload(services.get_binding(self.user))
        self.assertEqual(payload['session']['alive'], False)
        self.assertEqual(payload['session']['invalid_reason'], 'expired')

        PkuPortalSession.objects.filter(account=account).delete()
        payload = services.binding_payload(services.get_binding(self.user))
        self.assertIsNone(payload['session']['alive'])

    def test_locked_until_only_while_locked(self):
        account = self.bind()
        future = datetime.now() + timedelta(minutes=5)
        PkuAccount.objects.filter(pk=account.pk).update(locked_until=future)
        payload = services.binding_payload(services.get_binding(self.user))
        self.assertRegex(payload['locked_until'], ISO_RE)

        past = datetime.now() - timedelta(minutes=5)
        PkuAccount.objects.filter(pk=account.pk).update(locked_until=past)
        payload = services.binding_payload(services.get_binding(self.user))
        self.assertIsNone(payload['locked_until'])
