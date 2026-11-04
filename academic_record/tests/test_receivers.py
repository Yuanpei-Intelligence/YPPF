"""
Receiver tests: stored grades disappear when the grades consent is revoked
or the binding is removed, and survive everything else.
"""
from django.test import TestCase

from generic.models import User
from pku_account.models import PkuAccount
from pku_account.services import unbind, update_consents
from pku_account.signals import consent_changed
from academic_record.models import GradeRecord
from academic_record.tests.helpers import (
    bind,
    enable_portal,
    make_person,
    make_record,
)


class ConsentReceiverTests(TestCase):

    def setUp(self):
        enable_portal(self)
        self.user, self.person = make_person()
        self.other_user, self.other_person = make_person('ar_other', '别人')
        self.account = bind(self.user, consent_grades=True)
        self.other_account = bind(self.other_user, '2100010002', consent_grades=True)
        make_record(self.person, name='a')
        make_record(self.person, name='b', term_code='24-25-1')
        make_record(self.other_person, name='c')

    def mine(self):
        return GradeRecord.objects.filter(person=self.person)

    def theirs(self):
        return GradeRecord.objects.filter(person=self.other_person)

    def test_receiver_is_connected(self):
        consent_changed.send(sender=PkuAccount, account=self.account,
                             field='grades', granted=False)
        self.assertFalse(self.mine().exists())
        self.assertEqual(self.theirs().count(), 1)

    def test_revocation_deletes_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            update_consents(self.user, grades=False)
            # Nothing happens before the transaction commits.
            self.assertEqual(self.mine().count(), 2)
        self.assertEqual(len(callbacks), 1)
        self.assertFalse(self.mine().exists())
        self.assertEqual(self.theirs().count(), 1)

    def test_grant_keeps_rows(self):
        with self.captureOnCommitCallbacks(execute=True):
            update_consents(self.user, grades=True)
        self.assertEqual(self.mine().count(), 2)

    def test_other_field_keeps_rows(self):
        with self.captureOnCommitCallbacks(execute=True):
            update_consents(self.user, timetable=False)
            update_consents(self.user, timetable=True)
        self.assertEqual(self.mine().count(), 2)
        consent_changed.send(sender=PkuAccount, account=self.account,
                             field='timetable', granted=False)
        self.assertEqual(self.mine().count(), 2)

    def test_revocation_through_login(self):
        with self.captureOnCommitCallbacks(execute=True):
            bind(self.user, consent_grades=False)
        self.assertFalse(self.mine().exists())
        self.assertEqual(self.theirs().count(), 1)

    def test_login_without_decision_keeps_rows(self):
        with self.captureOnCommitCallbacks(execute=True):
            bind(self.user)
            bind(self.user, consent_timetable=True)
        self.assertEqual(self.mine().count(), 2)

    def test_repeated_revocation_is_harmless(self):
        with self.captureOnCommitCallbacks(execute=True):
            update_consents(self.user, grades=False)
            update_consents(self.user, grades=False)
        self.assertFalse(self.mine().exists())

    def test_account_without_person_is_ignored(self):
        orphan = User.objects.create_user('ar_orphan', '无档案', User.Type.STUDENT,
                                          password='test')
        account = bind(orphan, '2100010003', consent_grades=True)
        consent_changed.send(sender=PkuAccount, account=account,
                             field='grades', granted=False)
        self.assertEqual(self.mine().count(), 2)
        self.assertEqual(self.theirs().count(), 1)


class BindingDeletedReceiverTests(TestCase):

    def setUp(self):
        enable_portal(self)
        self.user, self.person = make_person()
        self.other_user, self.other_person = make_person('ar_other', '别人')
        bind(self.user, consent_grades=True)
        bind(self.other_user, '2100010002', consent_grades=True)
        make_record(self.person, name='a')
        make_record(self.other_person, name='c')

    def test_unbind_deletes_stored_rows(self):
        unbind(self.user)
        self.assertFalse(GradeRecord.objects.filter(person=self.person).exists())
        self.assertEqual(GradeRecord.objects.filter(person=self.other_person).count(), 1)
        unbind(self.user)  # no binding any more: nothing to do

    def test_unbind_only_affects_that_persons_rows(self):
        _, unbound = make_person('ar_unbound', '无绑定')
        make_record(unbound, name='x')
        unbind(self.user)
        self.assertEqual(GradeRecord.objects.filter(person=unbound).count(), 1)
        self.assertEqual(GradeRecord.objects.filter(person=self.other_person).count(), 1)
