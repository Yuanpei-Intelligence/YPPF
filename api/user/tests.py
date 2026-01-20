from django.test import TestCase

from app.models import NaturalPerson
from generic.models import User
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
        NaturalPerson.objects.create(self.user, name="john")

        self.special_user = User.objects.create_user(
            "andy",
            "andy",
            usertype=User.Type.SPECIAL,
            password="andypw",
        )

        self.client = APIClient()

    def test_me_requires_auth(self):
        resp = self.client.get("/api/v2/user/me/")
        self.assertEqual(resp.status_code, 401)

    def test_me_returns_self(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get("/api/v2/user/me/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["username"], "john")
        self.assertEqual(payload["name"], "john")
        self.assertTrue(payload["is_person"])

    def test_special_user(self):
        """
        users without a natural person or organization should not break the system
        """
        self.client.force_authenticate(self.special_user)
        resp = self.client.get("/api/v2/user/me")


