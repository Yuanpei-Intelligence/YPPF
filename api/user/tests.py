from django.test import TestCase

from app.models import NaturalPerson
from generic.models import User


class MeApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "john",
            "john",
            usertype=User.Type.PERSON,
            password="johnpassword",
        )
        NaturalPerson.objects.create(cls.user, name="john")

    def test_me_requires_auth(self):
        resp = self.client.get("/api/v2/user/me/")
        # With SessionAuthentication, DRF typically returns 403 for anonymous.
        self.assertIn(resp.status_code, (401, 403))

    def test_me_returns_self(self):
        self.client.force_login(self.user)
        resp = self.client.get("/api/v2/user/me/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["username"], "john")
        self.assertEqual(payload["name"], "john")
        self.assertTrue(payload["is_person"])


