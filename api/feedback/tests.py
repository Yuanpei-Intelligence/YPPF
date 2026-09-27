"""
Tests for feedback API.
"""
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from rest_framework import status as http_status

from generic.models import User
from app.models import NaturalPerson, Organization, OrganizationType
from feedback.models import FeedbackType, Feedback
from rollout.config import CONFIG as rollout_config
from rollout.models import Feature


class FeedbackAPITestCase(APITestCase):
    """Test cases for Feedback API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        # 个人用户（发布者）
        self.person_user = User.objects.create_user(
            username="feedback_person",
            name="反馈用户",
            usertype=User.Type.PERSON,
            password="testpass123",
        )
        self.person = NaturalPerson.objects.create(
            self.person_user, name="反馈用户"
        )

        # 教师（用于 incharge，避免“给管理小组发反馈”被拒）
        self.teacher_user = User.objects.create_user(
            username="feedback_teacher",
            name="负责老师",
            usertype=User.Type.TEACHER,
            password="testpass123",
        )
        self.teacher = NaturalPerson.objects.create(
            self.teacher_user, name="负责老师"
        )

        # 组织类型与小组
        self.org_type = OrganizationType.objects.create(
            otype_id=100,
            otype_name="测试小组类型",
            incharge=self.teacher,
            job_name_list=["部长", "副部长", "部员", "干事"],
        )
        self.org_user = User.objects.create_user(
            username="feedback_org",
            name="测试小组",
            usertype=User.Type.ORG,
            password="testpass123",
        )
        self.org = Organization.objects.create(
            organization_id=self.org_user,
            oname="测试接收小组",
            otype=self.org_type,
        )

        # 反馈类型
        self.feedback_type = FeedbackType.objects.create(
            id=1,
            name="测试反馈类型",
            org_type=self.org_type,
            org=self.org,
            flexible=FeedbackType.Flexible.ALL_DEFAULT,
        )

        # 草稿反馈
        self.draft_feedback = Feedback.objects.create(
            type=self.feedback_type,
            title="草稿标题",
            content="草稿内容",
            person=self.person,
            org_type=self.org_type,
            org=self.org,
            publisher_public=False,
            issue_status=Feedback.IssueStatus.DRAFTED,
        )

        # 已发布反馈
        self.issued_feedback = Feedback.objects.create(
            type=self.feedback_type,
            title="已发布标题",
            content="已发布内容",
            person=self.person,
            org_type=self.org_type,
            org=self.org,
            publisher_public=True,
            issue_status=Feedback.IssueStatus.ISSUED,
        )

    def test_list_feedback_unauthenticated(self):
        """未认证用户不能访问列表."""
        url = reverse("api:feedback:feedback-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_list_feedback_as_person(self):
        """个人用户看到自己发出的反馈列表."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        ids = [item["id"] for item in response.data]
        self.assertIn(self.draft_feedback.id, ids)
        self.assertIn(self.issued_feedback.id, ids)

    def test_list_feedback_as_org(self):
        """组织用户看到收到的反馈列表."""
        self.client.force_authenticate(user=self.org_user)
        url = reverse("api:feedback:feedback-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_feedback_filter_issue_status(self):
        """按发布状态筛选."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        response = self.client.get(
            url, {"issue_status": Feedback.IssueStatus.DRAFTED}
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.draft_feedback.id)
        self.assertEqual(
            response.data[0]["issue_status"], Feedback.IssueStatus.DRAFTED
        )

    def test_list_feedback_ordering(self):
        """列表支持排序."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        response = self.client.get(url, {"ordering": "-feedback_time"})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_types_list(self):
        """获取反馈类型列表."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-types")
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 1)
        first = response.data[0]
        self.assertIn("id", first)
        self.assertIn("name", first)
        self.assertEqual(first["name"], "测试反馈类型")

    def test_types_list_unauthenticated(self):
        """未认证不能访问类型列表."""
        url = reverse("api:feedback:feedback-types")
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_create_feedback_draft(self):
        """创建草稿反馈."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        payload = {
            "type": "测试反馈类型",
            "title": "新建草稿",
            "content": "新建草稿内容",
            "otype": "测试小组类型",
            "org": "测试接收小组",
            "publisher_public": False,
            "post_type": "save",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "新建草稿")
        self.assertEqual(
            response.data["issue_status"], Feedback.IssueStatus.DRAFTED
        )
        self.assertEqual(response.data["type_name"], "测试反馈类型")

    def test_create_feedback_direct_submit(self):
        """直接提交反馈."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        payload = {
            "type": "测试反馈类型",
            "title": "直接提交标题",
            "content": "直接提交内容",
            "otype": "测试小组类型",
            "org": "测试接收小组",
            "publisher_public": True,
            "post_type": "directly_submit",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["issue_status"], Feedback.IssueStatus.ISSUED
        )

    def test_create_feedback_org_forbidden(self):
        """组织账号不能创建反馈."""
        self.client.force_authenticate(user=self.org_user)
        url = reverse("api:feedback:feedback-list")
        payload = {
            "type": "测试反馈类型",
            "title": "标题",
            "content": "内容",
            "otype": "测试小组类型",
            "org": "测试接收小组",
            "publisher_public": False,
            "post_type": "save",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_create_feedback_invalid_type(self):
        """无效反馈类型返回 400."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        payload = {
            "type": "不存在的类型",
            "title": "标题",
            "content": "内容",
            "otype": "测试小组类型",
            "org": "测试接收小组",
            "publisher_public": False,
            "post_type": "save",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_direct_submit_requires_org(self):
        """直接提交时必须填写 otype 和 org."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse("api:feedback:feedback-list")
        payload = {
            "type": "测试反馈类型",
            "title": "标题",
            "content": "内容",
            "otype": "",
            "org": "",
            "publisher_public": False,
            "post_type": "directly_submit",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_retrieve_feedback_as_publisher(self):
        """发布者可查看自己的反馈详情."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.issued_feedback.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.issued_feedback.id)
        self.assertEqual(response.data["title"], "已发布标题")

    def test_retrieve_feedback_as_org(self):
        """接收组织可查看反馈详情."""
        self.client.force_authenticate(user=self.org_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.issued_feedback.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

    def test_retrieve_feedback_not_found(self):
        """不存在的反馈返回 404."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": 99999},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_partial_update_draft_modify(self):
        """修改草稿内容."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.draft_feedback.id},
        )
        payload = {
            "title": "修改后标题",
            "content": "修改后内容",
            "post_type": "modify",
        }
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "修改后标题")
        self.assertEqual(response.data["content"], "修改后内容")
        self.draft_feedback.refresh_from_db()
        self.assertEqual(self.draft_feedback.title, "修改后标题")

    def test_partial_update_submit_draft(self):
        """提交草稿."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.draft_feedback.id},
        )
        payload = {
            "title": self.draft_feedback.title,
            "content": self.draft_feedback.content,
            "otype": "测试小组类型",
            "org": "测试接收小组",
            "publisher_public": False,
            "post_type": "submit_draft",
        }
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(
            response.data["issue_status"], Feedback.IssueStatus.ISSUED
        )
        self.draft_feedback.refresh_from_db()
        self.assertEqual(
            self.draft_feedback.issue_status, Feedback.IssueStatus.ISSUED
        )

    def test_partial_update_non_draft_forbidden(self):
        """不能修改已发布的反馈（仅允许改草稿）."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.issued_feedback.id},
        )
        payload = {
            "title": "想改标题",
            "post_type": "modify",
        }
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_partial_update_other_person_forbidden(self):
        """不能修改他人反馈."""
        other_user = User.objects.create_user(
            username="other_person",
            name="其他人",
            usertype=User.Type.PERSON,
            password="testpass123",
        )
        other_person = NaturalPerson.objects.create(other_user, name="其他人")
        self.client.force_authenticate(user=other_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.draft_feedback.id},
        )
        payload = {"title": "篡改", "post_type": "modify"}
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_destroy_draft(self):
        """删除草稿."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.draft_feedback.id},
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, http_status.HTTP_204_NO_CONTENT)
        self.draft_feedback.refresh_from_db()
        self.assertEqual(
            self.draft_feedback.issue_status, Feedback.IssueStatus.DELETED
        )

    def test_destroy_issued_forbidden(self):
        """不能通过 API 删除已发布的反馈（仅能删草稿）."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.issued_feedback.id},
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_destroy_other_person_forbidden(self):
        """不能删除他人反馈."""
        other_user = User.objects.create_user(
            username="other_person2",
            name="其他人2",
            usertype=User.Type.PERSON,
            password="testpass123",
        )
        NaturalPerson.objects.create(other_user, name="其他人2")
        self.client.force_authenticate(user=other_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.draft_feedback.id},
        )
        response = self.client.delete(url)
        self.assertEqual(response.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_serializer_fields(self):
        """列表/详情包含预期字段."""
        self.client.force_authenticate(user=self.person_user)
        url = reverse(
            "api:feedback:feedback-detail",
            kwargs={"pk": self.issued_feedback.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        data = response.data
        for field in (
            "id",
            "type",
            "type_name",
            "title",
            "content",
            "person",
            "person_name",
            "org_type_name",
            "org_name",
            "issue_status",
            "issue_status_display",
            "solve_status",
            "solve_status_display",
            "feedback_time",
            "publisher_public",
        ):
            self.assertIn(field, data, f"Field '{field}' missing in response")


class PreviewFeedbackAPITestCase(APITestCase):
    """Feedback about an experimental feature must reach the configured group."""

    def setUp(self):
        self.client = APIClient()
        self.person_user = User.objects.create_user(
            username="preview_feedback_person",
            name="体验用户",
            usertype=User.Type.STUDENT,
            password="testpass123",
        )
        self.person = NaturalPerson.objects.create(self.person_user, name="体验用户")
        teacher_user = User.objects.create_user(
            username="preview_feedback_teacher",
            name="负责老师",
            usertype=User.Type.TEACHER,
            password="testpass123",
        )
        teacher = NaturalPerson.objects.create(
            teacher_user, name="负责老师", identity=NaturalPerson.Identity.TEACHER
        )
        self.org_type = OrganizationType.objects.create(
            otype_id=101,
            otype_name="项目组类型",
            incharge=teacher,
            job_name_list=["成员"],
        )
        project_user = User.objects.create_user(
            username="preview_feedback_project",
            name="项目组",
            usertype=User.Type.ORG,
            password="testpass123",
        )
        self.org = Organization.objects.create(
            organization_id=project_user,
            oname=rollout_config.feedback_org_name,
            otype=self.org_type,
        )
        other_user = User.objects.create_user(
            username="preview_feedback_other",
            name="其他小组",
            usertype=User.Type.ORG,
            password="testpass123",
        )
        self.other_org = Organization.objects.create(
            organization_id=other_user, oname="其他小组", otype=self.org_type
        )
        self.preview_type = FeedbackType.objects.create(
            id=11,
            name=rollout_config.feedback_type_name,
            org_type=self.org_type,
            org=self.org,
            flexible=FeedbackType.Flexible.ALL_DEFAULT,
        )
        FeedbackType.objects.create(
            id=12,
            name="普通反馈",
            org_type=self.org_type,
            org=self.other_org,
            flexible=FeedbackType.Flexible.ALL_DEFAULT,
        )
        Feature.objects.create(key="grades", name="我的成绩", stage=Feature.Stage.PREVIEW)

        notification = mock.patch("api.feedback.views.make_relevant_notification")
        notification.start()
        self.addCleanup(notification.stop)

        self.client.force_authenticate(user=self.person_user)
        self.list_url = reverse("api:feedback:feedback-list")

    def _payload(self, **overrides):
        payload = {
            "type": rollout_config.feedback_type_name,
            "title": "成绩页显示错位",
            "content": "第二学期的成绩没有对齐",
            "otype": self.org_type.otype_name,
            "org": rollout_config.feedback_org_name,
            "publisher_public": False,
            "post_type": "directly_submit",
            "feature_key": "grades",
            "client_info": {
                "platform": "mp-weixin",
                "env_version": "release",
                "app_version": "1.4.0",
            },
        }
        payload.update(overrides)
        return payload

    def test_preview_feedback_records_feature_and_client(self):
        response = self.client.post(self.list_url, self._payload(), format="json")
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["feature_key"], "grades")

        feedback = Feedback.objects.get(pk=response.data["id"])
        self.assertEqual(feedback.feature_key, "grades")
        self.assertEqual(feedback.client_info["env_version"], "release")
        self.assertEqual(feedback.type, self.preview_type)
        self.assertEqual(feedback.org, self.org)
        self.assertFalse(feedback.publisher_public)

    def test_unknown_feature_key_is_rejected(self):
        response = self.client.post(
            self.list_url, self._payload(feature_key="missing"), format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn("feature_key", response.data)

    def test_preview_feedback_to_another_group_is_rejected(self):
        response = self.client.post(
            self.list_url, self._payload(org="其他小组"), format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn("org", response.data)
        self.assertFalse(Feedback.objects.exists())

    def test_preview_feedback_with_another_type_is_rejected(self):
        response = self.client.post(
            self.list_url, self._payload(type="普通反馈"), format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn("type", response.data)

    def test_client_info_is_bounded(self):
        invalid_values = [
            {f"key{index}": "value" for index in range(9)},
            {"k" * 33: "value"},
            {"page": "p" * 129},
        ]
        for client_info in invalid_values:
            with self.subTest(client_info=client_info):
                response = self.client.post(
                    self.list_url, self._payload(client_info=client_info), format="json")
                self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
                self.assertIn("client_info", response.data)

    def test_regular_feedback_is_unaffected(self):
        payload = self._payload(type="普通反馈", org="其他小组")
        del payload["feature_key"]
        del payload["client_info"]
        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED, response.data)
        feedback = Feedback.objects.get(pk=response.data["id"])
        self.assertEqual(feedback.feature_key, "")
        self.assertEqual(feedback.client_info, {})

    def test_submitting_a_preview_draft_checks_routing(self):
        draft = Feedback.objects.create(
            type=self.preview_type,
            title="草稿标题",
            content="草稿内容",
            person=self.person,
            org_type=self.org_type,
            org=self.org,
            feature_key="grades",
            issue_status=Feedback.IssueStatus.DRAFTED,
        )
        detail_url = reverse("api:feedback:feedback-detail", kwargs={"pk": draft.id})

        response = self.client.patch(detail_url, {
            "post_type": "submit_draft",
            "otype": self.org_type.otype_name,
            "org": "其他小组",
        }, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn("org", response.data)

        response = self.client.patch(detail_url, {
            "post_type": "submit_draft",
            "otype": self.org_type.otype_name,
            "org": rollout_config.feedback_org_name,
        }, format="json")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK, response.data)
        draft.refresh_from_db()
        self.assertEqual(draft.issue_status, Feedback.IssueStatus.ISSUED)

    def test_preview_draft_may_omit_the_receiving_group(self):
        response = self.client.post(
            self.list_url,
            self._payload(post_type="save", otype="", org=""),
            format="json",
        )
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED, response.data)
        feedback = Feedback.objects.get(pk=response.data["id"])
        self.assertEqual(feedback.issue_status, Feedback.IssueStatus.DRAFTED)
        self.assertEqual(feedback.feature_key, "grades")

    def test_modifying_a_preview_draft_keeps_routing(self):
        draft = Feedback.objects.create(
            type=self.preview_type,
            title="草稿标题",
            content="草稿内容",
            person=self.person,
            org_type=self.org_type,
            org=self.org,
            feature_key="grades",
            issue_status=Feedback.IssueStatus.DRAFTED,
        )
        detail_url = reverse("api:feedback:feedback-detail", kwargs={"pk": draft.id})
        for change, field in (({"org": "其他小组"}, "org"), ({"type": "普通反馈"}, "type")):
            with self.subTest(change=change):
                response = self.client.patch(
                    detail_url, {"post_type": "modify", **change}, format="json")
                self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)
        draft.refresh_from_db()
        self.assertEqual(draft.org, self.org)
        self.assertEqual(draft.type, self.preview_type)
