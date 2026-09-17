"""
Tests of ``pku_account.signals.consent_changed``: sent for every explicit
consent decision of ``update_consents`` / ``login_and_bind``, only after
the transaction committed, never for ``None``.
"""
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.db import transaction
from django.test import TestCase

from app.models import NaturalPerson
from generic.models import User
from pku_account import services
from pku_account.config import PkuPortalConfig
from pku_account.extern.portal import PortalClient
from pku_account.models import PkuAccount
from pku_account.signals import CONSENT_FIELDS, consent_changed

PASSWORD = 'S3cret-Pa55!'
PKU_ID = '2100010001'


def make_person(username: str, name: str = '测试用户') -> User:
    user = User.objects.create_user(
        username, name, User.Type.STUDENT, password='yppf-password',
    )
    NaturalPerson.objects.create(user, name=name)
    return user


def fake_client() -> PortalClient:
    return PortalClient.from_cookies({'JSESSIONID': 'portal-session'})


class ConsentChangedSignalTests(TestCase):

    def setUp(self):
        self.user = make_person('S000001')
        for name, value in (
            ('enabled', True),
            ('session_key', Fernet.generate_key().decode()),
        ):
            patcher = patch.object(PkuPortalConfig, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.received = []
        consent_changed.connect(self.receiver, dispatch_uid='test_signals')
        self.addCleanup(consent_changed.disconnect, dispatch_uid='test_signals')

    def receiver(self, sender, **kwargs):
        self.received.append((sender, kwargs['account'], kwargs['field'],
                              kwargs['granted']))

    def bind(self, **kwargs) -> PkuAccount:
        with patch.object(PortalClient, 'login', return_value=fake_client()):
            return services.login_and_bind(self.user, PKU_ID, PASSWORD, **kwargs)

    def test_documented_fields(self):
        self.assertEqual(CONSENT_FIELDS, ('timetable', 'grades'))

    def test_update_consents_sends_each_explicit_decision_after_commit(self):
        self.bind()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            account = services.update_consents(self.user, grades=False)
            self.assertEqual(self.received, [])
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(self.received, [(PkuAccount, account, 'grades', False)])

        self.received.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.update_consents(self.user, timetable=True, grades=True)
        self.assertEqual([(field, granted) for _, _, field, granted in self.received],
                         [('timetable', True), ('grades', True)])

        self.received.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.update_consents(self.user, timetable=False)
        self.assertEqual([(field, granted) for _, _, field, granted in self.received],
                         [('timetable', False)])

    def test_same_value_is_still_announced(self):
        self.bind(consent_grades=False)
        self.received.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.update_consents(self.user, grades=False)
        self.assertEqual([(field, granted) for _, _, field, granted in self.received],
                         [('grades', False)])

    def test_login_and_bind_sends_only_explicit_flags(self):
        with self.captureOnCommitCallbacks(execute=True):
            account = self.bind(consent_grades=True)
        self.assertEqual(self.received, [(PkuAccount, account, 'grades', True)])

        self.received.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.bind()
        self.assertEqual(self.received, [])

        with self.captureOnCommitCallbacks(execute=True):
            self.bind(consent_timetable=True, consent_grades=False)
        self.assertEqual([(field, granted) for _, _, field, granted in self.received],
                         [('timetable', True), ('grades', False)])

    def test_not_sent_when_the_transaction_rolls_back(self):
        self.bind()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    services.update_consents(self.user, grades=False)
                    raise RuntimeError('abort')
        self.assertEqual(callbacks, [])
        self.assertEqual(self.received, [])

    def test_not_sent_when_unbound(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(services.NotBound):
                services.update_consents(self.user, grades=False)
        self.assertEqual(callbacks, [])
        self.assertEqual(self.received, [])
