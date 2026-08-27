from datetime import datetime
from unittest import mock

from app.models import NaturalPerson
from generic.models import User
from rest_framework import status
from rest_framework.test import APIClient, APITestCase


class MeApiTest(APITestCase):
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            "john",
            "john",
            usertype=User.Type.PERSON,
            password="johnpassword",
        )
        self.person = NaturalPerson.objects.create(self.user, name="john")

        self.special_user = User.objects.create_user(
            "andy",
            "andy",
            usertype=User.Type.SPECIAL,
            password="andypw",
        )

        self.client = APIClient()

    def assert_error(self, response, expected_status, expected_code):
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(set(response.data), {"code", "message", "errors"})
        self.assertEqual(response.data["code"], expected_code)
        self.assertIsInstance(response.data["message"], str)
        self.assertIsInstance(response.data["errors"], dict)

    def test_me_requires_auth(self):
        resp = self.client.get("/api/v2/user/me/")
        self.assert_error(
            resp,
            status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
        )
        self.assertEqual(resp.data["errors"], {})

    def test_me_returns_self(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get("/api/v2/user/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payload = resp.json()
        self.assertEqual(payload["username"], "john")
        self.assertEqual(payload["name"], "john")
        self.assertTrue(payload["is_person"])

    def test_special_user(self):
        """
        users without a natural person or organization should not break the system
        """
        self.client.force_authenticate(self.special_user)
        resp = self.client.get("/api/v2/user/me/")

        self.assert_error(
            resp,
            status.HTTP_403_FORBIDDEN,
            "permission_denied",
        )
        self.assertEqual(resp.data["message"], "该账号不可登录小程序。")
        self.assertEqual(resp.data["errors"], {})

    def test_daily_login_requires_auth(self):
        resp = self.client.post("/api/v2/user/daily-login/")

        self.assert_error(
            resp,
            status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
        )
        self.assertEqual(resp.data["errors"], {})

    @mock.patch(
        "api.user.views.add_signin_point",
        return_value=(1, "签到成功，获得 1 点元气值。"),
    )
    def test_daily_login_awards_first_login_of_day(self, add_point_mock):
        self.client.force_authenticate(self.user)
        fixed_now = datetime(2026, 8, 27, 10, 30)

        with mock.patch("api.user.views.datetime") as datetime_mock:
            datetime_mock.now.return_value = fixed_now
            resp = self.client.post("/api/v2/user/daily-login/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, {"message": "签到成功，获得 1 点元气值。"})
        add_point_mock.assert_called_once_with(self.user)
        self.person.refresh_from_db()
        self.assertEqual(self.person.last_time_login, fixed_now)

    @mock.patch("api.user.views.add_signin_point")
    def test_daily_login_is_idempotent_within_the_day(self, add_point_mock):
        fixed_now = datetime(2026, 8, 27, 10, 30)
        self.person.last_time_login = fixed_now
        self.person.save(update_fields=["last_time_login"])
        self.client.force_authenticate(self.user)

        with mock.patch("api.user.views.datetime") as datetime_mock:
            datetime_mock.now.return_value = fixed_now
            resp = self.client.post("/api/v2/user/daily-login/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, {"message": "今日已登录"})
        add_point_mock.assert_not_called()

    def test_daily_login_rejects_get(self):
        self.client.force_authenticate(self.user)

        resp = self.client.get("/api/v2/user/daily-login/")

        self.assert_error(
            resp,
            status.HTTP_405_METHOD_NOT_ALLOWED,
            "method_not_allowed",
        )
        self.assertEqual(resp.data["errors"], {})
