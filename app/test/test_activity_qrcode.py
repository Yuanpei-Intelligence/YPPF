from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from app.activity_utils import build_legacy_checkin_url
from app.models import (
    Activity,
    ActivityPhoto,
    NaturalPerson,
    Organization,
    OrganizationType,
    User,
)
from boot.config import GLOBAL_CONFIG


class ActivityQrcodeHelperTestCase(SimpleTestCase):
    def test_build_legacy_checkin_url_contains_auth(self):
        request = RequestFactory().get("/fake")
        activity = SimpleNamespace(id=42)

        url = build_legacy_checkin_url(request, activity)

        self.assertIn(f"{GLOBAL_CONFIG.base_url}/checkinActivity/42?auth=", url)


class ActivityQrcodeViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        teacher_user = User.objects.create_user(
            "teacher",
            "Teacher",
            User.Type.TEACHER,
            password="pw",
            is_newuser=False,
        )
        cls.teacher = NaturalPerson.objects.create(
            teacher_user,
            name="Teacher",
            identity=NaturalPerson.Identity.TEACHER,
        )

        cls.otype = OrganizationType.objects.create(
            otype_id=9001,
            otype_name="测试组织类型",
            incharge=cls.teacher,
            job_name_list=["负责人", "副负责人", "成员", "干事"],
        )

        cls.owner_user = User.objects.create_user(
            "owner_org",
            "Owner Org",
            User.Type.ORG,
            password="pw",
            is_newuser=False,
        )
        cls.owner_org = Organization.objects.create(
            organization_id=cls.owner_user,
            oname="Owner Org",
            otype=cls.otype,
        )

        cls.other_user = User.objects.create_user(
            "other_org",
            "Other Org",
            User.Type.ORG,
            password="pw",
            is_newuser=False,
        )
        cls.other_org = Organization.objects.create(
            organization_id=cls.other_user,
            oname="Other Org",
            otype=cls.otype,
        )

        cls.activity = Activity.objects.create(
            title="二维码测试活动",
            organization_id=cls.owner_org,
            start=datetime.now() + timedelta(hours=2),
            end=datetime.now() + timedelta(hours=3),
            apply_end=datetime.now() + timedelta(minutes=10),
            location="测试地点",
            introduction="测试简介",
            need_checkin=True,
            status=Activity.Status.WAITING,
            valid=True,
            examine_teacher=cls.teacher,
        )
        ActivityPhoto.objects.create(
            type=ActivityPhoto.PhotoType.ANNOUNCE,
            activity=cls.activity,
        )

    def test_get_activity_info_old_qrcode_returns_png(self):
        self.client.force_login(self.owner_user)

        response = self.client.get(
            "/getActivityInfo/",
            {
                "activityid": self.activity.id,
                "infotype": "qrcode",
                "version": "old",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_get_activity_info_new_qrcode_returns_wechat_bytes(self):
        self.client.force_login(self.owner_user)

        with patch(
            "app.activity_views.fetch_miniprogram_checkin_qrcode",
            return_value=(b"mini-program-image", "image/jpeg"),
        ) as mocked_fetch:
            response = self.client.get(
                "/getActivityInfo/",
                {
                    "activityid": self.activity.id,
                    "infotype": "qrcode",
                    "version": "new",
                },
            )

        mocked_fetch.assert_called_once_with(self.activity)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, b"mini-program-image")

    def test_get_activity_info_non_owner_is_rejected(self):
        self.client.force_login(self.other_user)

        with self.assertRaisesMessage(AssertionError, "不是活动的组织者"):
            self.client.get(
                "/getActivityInfo/",
                {
                    "activityid": self.activity.id,
                    "infotype": "qrcode",
                    "version": "old",
                },
            )

    def test_view_activity_contains_both_qrcode_urls(self):
        self.client.force_login(self.owner_user)

        response = self.client.get(f"/viewActivity/{self.activity.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"/getActivityInfo/?activityid={self.activity.id}&infotype=qrcode&version=new",
        )
        self.assertContains(
            response,
            f"/getActivityInfo/?activityid={self.activity.id}&infotype=qrcode&version=old",
        )
