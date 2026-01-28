"""
Unit tests for organization subscription API endpoints.

Tests SubscriptionListView (GET subscriptions/) and
SubscriptionUpdateView (POST subscriptions/update/).
"""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from app.models import NaturalPerson, Organization, OrganizationType
from generic.models import User


class SubscriptionListViewTest(APITestCase):
    """Tests for GET /api/v2/org/subscriptions/ (SubscriptionListView)."""

    def setUp(self):
        self.client = APIClient()
        # Person user
        self.person_user = User.objects.create_user(
            "person1",
            "Person One",
            usertype=User.Type.PERSON,
            password="testpass",
        )
        NaturalPerson.objects.create(self.person_user, name="Person One")
        # Organization user
        self.org_user = User.objects.create_user(
            "org1",
            "Org One",
            usertype=User.Type.ORG,
            password="testpass",
        )
        otype = OrganizationType.objects.create(
            otype_id=1,
            otype_name="TestType",
            allow_unsubscribe=True,
        )
        Organization.objects.create(
            organization_id=self.org_user,
            oname="org1",
            otype=otype,
            status=True,
        )

    def _url(self):
        return reverse("api:org:subscription-list")

    def test_subscription_list_requires_auth(self):
        """Unauthenticated request returns 401."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_subscription_list_person_returns_200(self):
        """Authenticated person gets 200 and correct structure."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("is_person", data)
        self.assertIn("readonly", data)
        self.assertIn("organization_types", data)
        self.assertTrue(data["is_person"])
        self.assertFalse(data["readonly"])
        self.assertIsInstance(data["organization_types"], list)

    def test_subscription_list_org_returns_200(self):
        """Authenticated organization gets 200 with readonly true."""
        self.client.force_authenticate(user=self.org_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["is_person"])
        self.assertTrue(data["readonly"])
        self.assertIsInstance(data["organization_types"], list)

    def test_subscription_list_organization_types_structure(self):
        """Response organization_types have otype_id, otype_name, organizations."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for ot in response.json().get("organization_types", []):
            self.assertIn("otype_id", ot)
            self.assertIn("otype_name", ot)
            self.assertIn("allow_unsubscribe", ot)
            self.assertIn("organizations", ot)
            for org in ot["organizations"]:
                self.assertIn("subscribed", org)


class SubscriptionUpdateViewTest(APITestCase):
    """Tests for POST /api/v2/org/subscriptions/update/ (SubscriptionUpdateView)."""

    def setUp(self):
        self.client = APIClient()
        self.person_user = User.objects.create_user(
            "person2",
            "Person Two",
            usertype=User.Type.PERSON,
            password="testpass",
        )
        self.me = NaturalPerson.objects.create(
            self.person_user, name="Person Two")

        self.org_user = User.objects.create_user(
            "org2",
            "Org Two",
            usertype=User.Type.ORG,
            password="testpass",
        )
        self.otype = OrganizationType.objects.create(
            otype_id=2,
            otype_name="UpdateTestType",
            allow_unsubscribe=True,
        )
        self.org = Organization.objects.create(
            organization_id=self.org_user,
            oname="org2",
            otype=self.otype,
            status=True,
        )

    def _url(self):
        return reverse("api:org:subscription-update")

    def test_subscription_update_requires_auth(self):
        """Unauthenticated request returns 401."""
        response = self.client.post(
            self._url(),
            {"id": self.org.organization_id.username, "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_subscription_update_org_forbidden(self):
        """Organization account gets 403 (only person can update)."""
        self.client.force_authenticate(user=self.org_user)
        response = self.client.post(
            self._url(),
            {"id": self.org.organization_id.username, "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subscription_update_validation_neither_id_nor_otype(self):
        """400 when neither id nor otype is provided."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_subscription_update_validation_both_id_and_otype(self):
        """400 when both id and otype are provided."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"id": "org2", "otype": 2, "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_subscription_update_single_org_subscribe(self):
        """Person can subscribe to a single org (remove from unsubscribe_list)."""
        self.me.unsubscribe_list.add(self.org)
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"id": self.org.organization_id.username, "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("成功订阅", data.get("message", ""))
        self.me.refresh_from_db()
        self.assertNotIn(self.org, self.me.unsubscribe_list.all())

    def test_subscription_update_single_org_unsubscribe(self):
        """Person can unsubscribe from a single org."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"id": self.org.organization_id.username, "status": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("成功取消订阅", data.get("message", ""))
        self.me.refresh_from_db()
        self.assertIn(self.org, self.me.unsubscribe_list.all())

    def test_subscription_update_single_org_nonexistent(self):
        """400 when id references non-existent organization."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"id": "nonexistent_org", "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_subscription_update_by_otype_subscribe(self):
        """Person can subscribe to all orgs of a type."""
        self.me.unsubscribe_list.add(self.org)
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"otype": self.otype.otype_id, "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("成功订阅", data.get("message", ""))
        self.me.refresh_from_db()
        self.assertNotIn(self.org, self.me.unsubscribe_list.all())

    def test_subscription_update_by_otype_unsubscribe(self):
        """Person can unsubscribe from all orgs of a type (when allow_unsubscribe)."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"otype": self.otype.otype_id, "status": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.me.refresh_from_db()
        self.assertIn(self.org, self.me.unsubscribe_list.all())

    def test_subscription_update_unsubscribe_not_allowed_single(self):
        """403 when unsubscribing from single org whose type has allow_unsubscribe=False."""
        self.otype.allow_unsubscribe = False
        self.otype.save()
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"id": self.org.organization_id.username, "status": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subscription_update_unsubscribe_not_allowed_by_otype(self):
        """403 when unsubscribing by otype and type has allow_unsubscribe=False."""
        self.otype.allow_unsubscribe = False
        self.otype.save()
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"otype": self.otype.otype_id, "status": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subscription_update_otype_nonexistent(self):
        """400 when otype references non-existent organization type."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            self._url(),
            {"otype": 99999, "status": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
