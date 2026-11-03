"""
Tests for the website feedback flow.
"""
from unittest import mock

from django.test import TestCase

from generic.models import User
from app.models import NaturalPerson, Organization, OrganizationType
from feedback.models import Feedback, FeedbackType
from rollout.config import CONFIG as rollout_config


class PreviewFeedbackWebsiteTests(TestCase):
    """The website must not route preview feedback away from its group."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="web_preview_person",
            name="体验用户",
            usertype=User.Type.STUDENT,
            password="testpass123",
        )
        # Skip the first-login agreement redirect of check_user_access.
        self.user.is_newuser = False
        self.user.save(update_fields=["is_newuser"])
        self.person = NaturalPerson.objects.create(self.user, name="体验用户")

        teacher_user = User.objects.create_user(
            username="web_preview_teacher",
            name="负责老师",
            usertype=User.Type.TEACHER,
            password="testpass123",
        )
        teacher = NaturalPerson.objects.create(
            teacher_user, name="负责老师", identity=NaturalPerson.Identity.TEACHER
        )
        self.otype = OrganizationType.objects.create(
            otype_id=102,
            otype_name="项目组类型",
            incharge=teacher,
            job_name_list=["成员"],
        )
        project_user = User.objects.create_user(
            username="web_preview_project",
            name="项目组",
            usertype=User.Type.ORG,
            password="testpass123",
        )
        self.org = Organization.objects.create(
            organization_id=project_user,
            oname=rollout_config.feedback_org_name,
            otype=self.otype,
        )
        other_user = User.objects.create_user(
            username="web_preview_other",
            name="其他小组",
            usertype=User.Type.ORG,
            password="testpass123",
        )
        self.other_org = Organization.objects.create(
            organization_id=other_user, oname="其他小组", otype=self.otype
        )
        self.preview_type = FeedbackType.objects.create(
            id=21,
            name=rollout_config.feedback_type_name,
            org_type=self.otype,
            org=self.org,
            flexible=FeedbackType.Flexible.ALL_DEFAULT,
        )
        FeedbackType.objects.create(
            id=22,
            name="普通反馈",
            org_type=self.otype,
            org=self.other_org,
            flexible=FeedbackType.Flexible.ALL_DEFAULT,
        )
        self.draft = Feedback.objects.create(
            type=self.preview_type,
            title="草稿标题",
            content="草稿内容",
            person=self.person,
            org_type=self.otype,
            org=self.org,
            feature_key="grades",
            issue_status=Feedback.IssueStatus.DRAFTED,
        )

        for target in (
            "feedback.views.unlock_achievement",
            "feedback.views.make_relevant_notification",
        ):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.force_login(self.user)

    def _post(self, **fields):
        data = {
            "type": rollout_config.feedback_type_name,
            "otype": self.otype.otype_name,
            "org": rollout_config.feedback_org_name,
            "title": "草稿标题",
            "content": "草稿内容",
            "publisher_public": "不公开",
            "post_type": "submit_draft",
        }
        data.update(fields)
        return self.client.post(
            f"/modifyFeedback/?feedback_id={self.draft.id}", data)

    def test_submitting_to_another_group_is_rejected(self):
        response = self._post(org="其他小组")
        self.assertEqual(response.status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.org, self.org)
        self.assertEqual(self.draft.issue_status, Feedback.IssueStatus.DRAFTED)

    def test_changing_the_type_is_rejected(self):
        self._post(post_type="modify", type="普通反馈", title="新标题")
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.type, self.preview_type)
        self.assertEqual(self.draft.title, "草稿标题")

    def test_submitting_with_the_configured_routing_succeeds(self):
        self._post()
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.issue_status, Feedback.IssueStatus.ISSUED)
        self.assertEqual(self.draft.org, self.org)
        self.assertEqual(self.draft.feature_key, "grades")
