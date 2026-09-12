"""
Tests for the rollout API.
"""
import json
from datetime import timedelta
from unittest import mock

from django.urls import reverse
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import (
    APIClient,
    APIRequestFactory,
    APITestCase,
    force_authenticate,
)
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from generic.models import User
from app.models import NaturalPerson, Organization, OrganizationType
from feedback.models import FeedbackType
from api.auth.views import _issue_jwt_for_user
from api.authentication import WxJWTAuthentication
from rollout.config import CONFIG, RolloutConfig
from rollout.models import Feature, PreviewMember
from rollout.permissions import FEATURE_NOT_ENABLED_MESSAGE, feature_permission


class GatedView(APIView):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated, feature_permission("demo")]

    def get(self, request):
        return Response({"ok": True})


class StandaloneGatedView(APIView):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [feature_permission("demo")]

    def get(self, request):
        return Response({"ok": True})


def create_student(username: str) -> User:
    user = User.objects.create_user(
        username=username, name=username, usertype=User.Type.STUDENT,
        password="testpass123",
    )
    # NaturalPerson.name holds at most 10 characters.
    NaturalPerson.objects.create(user, name="测试学生")
    return user


class RolloutAPITestCase(APITestCase):
    """Rollout state and preview channel endpoints."""

    def setUp(self):
        patcher = mock.patch.object(RolloutConfig, "preview_open", True)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = APIClient()
        self.student = create_student("api-rollout-student")
        self.org_user = User.objects.create_user(
            username="api-rollout-org", name="小组",
            usertype=User.Type.ORG, password="testpass123",
        )
        self.features_url = reverse("api:rollout:features")
        self.preview_url = reverse("api:rollout:preview")

    def _feature(self, key: str, stage: str, **fields) -> Feature:
        return Feature.objects.create(
            key=key, name=f"{key} 名称", description=f"{key} 说明",
            stage=stage, **fields,
        )

    def test_endpoints_require_a_token(self):
        self.assertEqual(self.client.get(self.features_url).status_code,
                         http_status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.post(self.preview_url).status_code,
                         http_status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.delete(self.preview_url).status_code,
                         http_status.HTTP_401_UNAUTHORIZED)

    def test_malformed_token_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")
        response = self.client.get(self.features_url)
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_expired_token_is_rejected(self):
        token = AccessToken.for_user(self.student)
        token.set_exp(lifetime=timedelta(minutes=-5))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get(self.features_url)
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_miniapp_token_reads_state_without_envelope_keys(self):
        token = _issue_jwt_for_user(self.student)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get(self.features_url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertNotIn("code", response.data)
        self.assertNotIn("data", response.data)

    def test_state_of_account_outside_the_preview_channel(self):
        self._feature("ga-feature", Feature.Stage.GA)
        self._feature("internal-feature", Feature.Stage.INTERNAL)
        self._feature("off-feature", Feature.Stage.OFF)
        self._feature("preview-feature", Feature.Stage.PREVIEW)
        self.client.force_authenticate(user=self.student)

        data = self.client.get(self.features_url).data
        self.assertEqual(data["account"], self.student.username)
        self.assertEqual(data["features"], {"ga-feature": True})
        self.assertEqual(data["experiments"], [{
            "key": "preview-feature",
            "name": "preview-feature 名称",
            "description": "preview-feature 说明",
            "stage": "preview",
            "enabled": False,
            "reason": None,
        }])
        self.assertEqual(data["preview"], {
            "joined": False,
            "joined_at": None,
            "can_join": True,
            "join_block_code": None,
            "join_block_message": None,
        })
        self.assertIsNone(data["feedback"])

    def test_internal_feature_is_listed_only_for_the_allow_list(self):
        feature = self._feature("internal-feature", Feature.Stage.INTERNAL)
        self.client.force_authenticate(user=self.student)
        self.assertEqual(self.client.get(self.features_url).data["experiments"], [])

        feature.allow_users.add(self.student)
        data = self.client.get(self.features_url).data
        self.assertEqual(data["features"], {"internal-feature": True})
        self.assertEqual(data["experiments"][0]["reason"], "allowlist")

    def test_join_and_leave_the_preview_channel(self):
        self._feature("preview-feature", Feature.Stage.PREVIEW)
        self.client.force_authenticate(user=self.student)

        response = self.client.post(self.preview_url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data["preview"]["joined"])
        self.assertIsNotNone(response.data["preview"]["joined_at"])
        self.assertEqual(response.data["features"], {"preview-feature": True})
        self.assertEqual(response.data["experiments"][0]["reason"], "preview")

        again = self.client.post(self.preview_url)
        self.assertEqual(again.status_code, http_status.HTTP_200_OK)
        self.assertEqual(PreviewMember.objects.filter(user=self.student).count(), 1)

        left = self.client.delete(self.preview_url)
        self.assertEqual(left.status_code, http_status.HTTP_200_OK)
        self.assertFalse(left.data["preview"]["joined"])
        self.assertEqual(left.data["features"], {})

        left_again = self.client.delete(self.preview_url)
        self.assertEqual(left_again.status_code, http_status.HTTP_200_OK)

    def test_organization_cannot_join(self):
        self.client.force_authenticate(user=self.org_user)
        self.assertEqual(
            self.client.get(self.features_url).data["account"], self.org_user.username)
        response = self.client.post(self.preview_url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)
        self.assertEqual(json.loads(response.content), {
            "code": "preview_person_only",
            "message": "只有个人账号可以加入体验通道。",
            "errors": {},
        })
        self.assertFalse(PreviewMember.objects.exists())

        preview = self.client.get(self.features_url).data["preview"]
        self.assertFalse(preview["can_join"])
        self.assertEqual(preview["join_block_code"], "preview_person_only")

    def test_closed_channel_rejects_joining(self):
        self.client.force_authenticate(user=self.student)
        with mock.patch.object(RolloutConfig, "preview_open", False):
            response = self.client.post(self.preview_url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "preview_closed")

    def test_feedback_routing_is_reported_once_configured(self):
        teacher = User.objects.create_user(
            username="api-rollout-teacher", name="老师",
            usertype=User.Type.TEACHER, password="testpass123",
        )
        teacher_person = NaturalPerson.objects.create(
            teacher, name="老师", identity=NaturalPerson.Identity.TEACHER)
        otype = OrganizationType.objects.create(
            otype_id=120, otype_name="项目组", incharge=teacher_person,
            job_name_list=["成员"],
        )
        org_user = User.objects.create_user(
            username="api-rollout-project", name="项目组账号",
            usertype=User.Type.ORG, password="testpass123",
        )
        org = Organization.objects.create(
            organization_id=org_user, oname=CONFIG.feedback_org_name, otype=otype)
        FeedbackType.objects.create(
            id=50, name=CONFIG.feedback_type_name, org_type=otype, org=org,
            flexible=FeedbackType.Flexible.ALL_DEFAULT,
        )
        self.client.force_authenticate(user=self.student)

        data = self.client.get(self.features_url).data
        self.assertEqual(data["feedback"], {
            "type_name": CONFIG.feedback_type_name,
            "org_type_name": "项目组",
            "org_name": CONFIG.feedback_org_name,
        })


class FeaturePermissionTestCase(APITestCase):
    """The permission used by endpoints of experimental features."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = GatedView.as_view()
        self.student = create_student("api-gated-student")

    def test_unauthenticated_request_still_gets_401(self):
        response = self.view(self.factory.get("/gated/"))
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_permission_without_is_authenticated_still_gives_401(self):
        response = StandaloneGatedView.as_view()(self.factory.get("/gated/"))
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_disabled_feature_gets_403_envelope(self):
        Feature.objects.create(key="demo", name="demo", stage=Feature.Stage.PREVIEW)
        request = self.factory.get("/gated/")
        force_authenticate(request, user=self.student)
        response = self.view(request)
        response.render()
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)
        self.assertEqual(json.loads(response.content), {
            "code": "feature_not_enabled",
            "message": FEATURE_NOT_ENABLED_MESSAGE,
            "errors": {},
            "feature": "demo",
        })

    def test_unknown_feature_gets_403(self):
        request = self.factory.get("/gated/")
        force_authenticate(request, user=self.student)
        response = self.view(request)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_enabled_feature_passes(self):
        feature = Feature.objects.create(
            key="demo", name="demo", stage=Feature.Stage.INTERNAL)
        feature.allow_users.add(self.student)
        request = self.factory.get("/gated/")
        force_authenticate(request, user=self.student)
        response = self.view(request)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
