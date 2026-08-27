import json
from datetime import datetime, timedelta

from django.conf import settings
from django.test import Client, TestCase

from app.models import (
    Activity,
    NaturalPerson,
    Notification,
    Organization,
    OrganizationType,
    Participation,
)
from boot.config import GLOBAL_CONFIG
from generic.models import User


class UnsafeGetMutationTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "v02-person",
            "V02 Person",
            User.Type.PERSON,
            password="test",
            is_newuser=False,
        )
        cls.person = NaturalPerson.objects.create(cls.user, name="V02 Person")
        cls.other_user = User.objects.create_user(
            "v02-other-person",
            "V02 Other",
            User.Type.PERSON,
            password="test",
            is_newuser=False,
        )
        cls.other_person = NaturalPerson.objects.create(
            cls.other_user,
            name="V02 Other",
        )
        cls.organization_type = OrganizationType.objects.create(
            otype_id=22002,
            otype_name="V02 Security Test",
            incharge=cls.person,
            job_name_list=["负责人", "成员"],
        )
        cls.organization_user = User.objects.create_user(
            "v02-org",
            "V02 Org",
            User.Type.ORG,
            password="test",
            is_newuser=False,
        )
        cls.organization = Organization.objects.create(
            organization_id=cls.organization_user,
            oname="V02 Org",
            otype=cls.organization_type,
        )

    def csrf_client(self, path):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        return client, token, response


class ActivityCheckinSecurityTestCase(UnsafeGetMutationTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        now = datetime.now()
        cls.activity = Activity.objects.create(
            title="V02 Check-in",
            organization_id=cls.organization,
            start=now - timedelta(minutes=30),
            end=now + timedelta(minutes=30),
            apply_end=now - timedelta(hours=1),
            location="V02 Room",
            introduction="Security regression test",
            need_checkin=True,
            status=Activity.Status.PROGRESSING,
            valid=True,
            examine_teacher=cls.person,
        )
        cls.participation = Participation.objects.create(
            activity=cls.activity,
            person=cls.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        cls.verifier = GLOBAL_CONFIG.hasher.encode(str(cls.activity.pk))

    def login(self, *, enforce_csrf_checks=False):
        client = Client(enforce_csrf_checks=enforce_csrf_checks)
        client.force_login(self.user)
        return client

    def test_get_and_head_show_confirmation_without_checking_in(self):
        client = self.login(enforce_csrf_checks=True)
        path = f"/checkinActivity/{self.activity.pk}"

        get_response = client.get(path, {"auth": self.verifier})
        self.participation.refresh_from_db()
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "确认活动签到")
        self.assertEqual(get_response["Cache-Control"], "no-store")
        self.assertEqual(get_response["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            self.participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )

        head_response = client.head(path, {"auth": self.verifier})
        self.participation.refresh_from_db()
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(
            self.participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )

    def test_inactive_person_is_rejected_inside_operation(self):
        path = f"/checkinActivity/{self.activity.pk}"
        client, token, _ = self.csrf_client(f"{path}?auth={self.verifier}")
        self.user.active = False
        self.user.save(update_fields=["active"])

        response = client.post(
            path,
            {"auth": self.verifier, "csrfmiddlewaretoken": token},
        )

        self.participation.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )

    def test_waiting_activity_outside_time_window_is_rejected(self):
        now = datetime.now()
        activity = Activity.objects.create(
            title="V02 Future Check-in",
            organization_id=self.organization,
            start=now + timedelta(hours=2),
            end=now + timedelta(hours=3),
            apply_end=now + timedelta(hours=1),
            location="Future Room",
            introduction="Security regression test",
            need_checkin=True,
            status=Activity.Status.WAITING,
            valid=True,
            examine_teacher=self.person,
        )
        participation = Participation.objects.create(
            activity=activity,
            person=self.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        verifier = GLOBAL_CONFIG.hasher.encode(str(activity.pk))
        path = f"/checkinActivity/{activity.pk}"
        client, token, _ = self.csrf_client(f"{path}?auth={verifier}")

        response = client.post(
            path,
            {"auth": verifier, "csrfmiddlewaretoken": token},
        )

        participation.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )

    def test_post_without_csrf_is_rejected_without_side_effect(self):
        client = self.login(enforce_csrf_checks=True)

        response = client.post(
            f"/checkinActivity/{self.activity.pk}",
            {"auth": self.verifier},
        )

        self.participation.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )

    def test_csrf_protected_post_checks_in_and_is_idempotent(self):
        path = f"/checkinActivity/{self.activity.pk}"
        client, token, _ = self.csrf_client(f"{path}?auth={self.verifier}")

        for expected_status in (
            Participation.AttendStatus.ATTENDED,
            Participation.AttendStatus.ATTENDED,
        ):
            response = client.post(
                path,
                {
                    "auth": self.verifier,
                    "csrfmiddlewaretoken": token,
                },
            )
            self.participation.refresh_from_db()
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.participation.status, expected_status)

    def test_wrong_verifier_does_not_check_in(self):
        path = f"/checkinActivity/{self.activity.pk}"
        client, token, _ = self.csrf_client(f"{path}?auth={self.verifier}")

        response = client.post(
            path,
            {"auth": "wrong", "csrfmiddlewaretoken": token},
        )

        self.participation.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )

    def test_unregistered_person_is_rejected(self):
        path = f"/checkinActivity/{self.activity.pk}"
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.other_user)
        response = client.get(path, {"auth": self.verifier})
        token = client.cookies[settings.CSRF_COOKIE_NAME].value

        response = client.post(
            path,
            {"auth": self.verifier, "csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 400)
        self.participation.refresh_from_db()
        self.assertEqual(
            self.participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )


class NotificationBulkSecurityTestCase(UnsafeGetMutationTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.unread = Notification.objects.create(
            receiver=cls.user,
            sender=cls.organization_user,
            status=Notification.Status.UNDONE,
            typename=Notification.Type.NEEDREAD,
            title="Unread",
            content="Unread test notification",
        )
        cls.read = Notification.objects.create(
            receiver=cls.user,
            sender=cls.organization_user,
            status=Notification.Status.DONE,
            typename=Notification.Type.NEEDREAD,
            title="Read",
            content="Read test notification",
        )
        cls.action_required = Notification.objects.create(
            receiver=cls.user,
            sender=cls.organization_user,
            status=Notification.Status.UNDONE,
            typename=Notification.Type.NEEDDO,
            title="Action required",
            content="Must not be bulk-read",
        )
        cls.other_unread = Notification.objects.create(
            receiver=cls.other_user,
            sender=cls.organization_user,
            status=Notification.Status.UNDONE,
            typename=Notification.Type.NEEDREAD,
            title="Other unread",
            content="Must remain untouched",
        )

    def login(self, *, enforce_csrf_checks=False):
        client = Client(enforce_csrf_checks=enforce_csrf_checks)
        client.force_login(self.user)
        return client

    def test_get_bulk_commands_have_no_side_effect(self):
        client = self.login(enforce_csrf_checks=True)

        for action in ("readall", "deleteall"):
            response = client.get("/notifications/", {"read_name": action})
            self.assertEqual(response.status_code, 200)

        self.unread.refresh_from_db()
        self.read.refresh_from_db()
        self.assertEqual(self.unread.status, Notification.Status.UNDONE)
        self.assertEqual(self.read.status, Notification.Status.DONE)

    def test_bulk_post_without_csrf_is_rejected(self):
        client = self.login(enforce_csrf_checks=True)

        response = client.post("/notifications/", {"action": "readall"})

        self.unread.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.unread.status, Notification.Status.UNDONE)

    def test_csrf_protected_readall_is_receiver_and_state_scoped(self):
        client, token, response = self.csrf_client("/notifications/")
        self.assertNotContains(response, "location.href = '/notifications/")
        self.assertContains(response, 'method="post"', count=2)

        response = client.post(
            "/notifications/",
            {"action": "readall", "csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 200)
        for notification in (
            self.unread,
            self.read,
            self.action_required,
            self.other_unread,
        ):
            notification.refresh_from_db()
        self.assertEqual(self.unread.status, Notification.Status.DONE)
        self.assertEqual(self.read.status, Notification.Status.DONE)
        self.assertEqual(
            self.action_required.status,
            Notification.Status.UNDONE,
        )
        self.assertEqual(self.other_unread.status, Notification.Status.UNDONE)

    def test_csrf_protected_deleteall_only_deletes_current_read(self):
        client, token, _ = self.csrf_client("/notifications/")

        response = client.post(
            "/notifications/",
            {"action": "deleteall", "csrfmiddlewaretoken": token},
        )

        self.assertEqual(response.status_code, 200)
        self.read.refresh_from_db()
        self.unread.refresh_from_db()
        self.other_unread.refresh_from_db()
        self.assertEqual(self.read.status, Notification.Status.DELETE)
        self.assertEqual(self.unread.status, Notification.Status.UNDONE)
        self.assertEqual(self.other_unread.status, Notification.Status.UNDONE)

    def test_single_notification_json_post_requires_csrf(self):
        client = self.login(enforce_csrf_checks=True)

        response = client.post(
            "/notifications/",
            data=json.dumps({"id": self.unread.pk, "function": "read"}),
            content_type="text/plain",
        )

        self.unread.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.unread.status, Notification.Status.UNDONE)

    def test_single_notification_json_post_accepts_csrf_header(self):
        client, token, _ = self.csrf_client("/notifications/")

        response = client.post(
            "/notifications/",
            data=json.dumps({"id": self.unread.pk, "function": "read"}),
            content_type="text/plain",
            HTTP_X_CSRFTOKEN=token,
        )

        self.unread.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(self.unread.status, Notification.Status.DONE)
