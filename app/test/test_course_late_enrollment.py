from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase

from app.course_utils import change_course_status, registration_status_change
from app.activity_utils import withdraw_activity_for_person
from app.models import (
    Activity,
    Course,
    CourseParticipant,
    NaturalPerson,
    ModifyPosition,
    Notification,
    Organization,
    OrganizationType,
    Participation,
    Position,
    User,
)
from app.org_utils import update_pos_application
from app.extern.wechat import WechatApp


class CourseLateEnrollmentTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        teacher_user = User.objects.create_user(
            "late_enrol_teacher",
            "Late enrol teacher",
            User.Type.TEACHER,
            password="pw",
        )
        cls.teacher = NaturalPerson.objects.create(
            teacher_user,
            name="Teacher",
            identity=NaturalPerson.Identity.TEACHER,
        )
        student_user = User.objects.create_user(
            "late_enrol_student",
            "Late enrol student",
            User.Type.STUDENT,
            password="pw",
        )
        cls.student = NaturalPerson.objects.create(
            student_user,
            name="Student",
            identity=NaturalPerson.Identity.STUDENT,
        )
        org_type = OrganizationType.objects.create(
            otype_id=9101,
            otype_name="Late enrol test type",
            incharge=cls.teacher,
            job_name_list=["负责人", "副负责人", "成员", "干事"],
        )
        org_user = User.objects.create_user(
            "late_enrol_org",
            "Late enrol org",
            User.Type.ORG,
            password="pw",
        )
        cls.organization = Organization.objects.create(
            organization_id=org_user,
            oname="Late enrol org",
            otype=org_type,
        )
        cls.course = Course.objects.create(
            name="Late enrol course",
            organization=cls.organization,
            type=Course.CourseType.INTELLECTUAL,
            status=Course.Status.STAGE2,
            capacity=20,
        )

    def create_activity(self, **overrides):
        now = datetime.now()
        fields = {
            "title": "Late enrol activity",
            "organization_id": self.organization,
            "start": now + timedelta(days=1),
            "end": now + timedelta(days=1, hours=2),
            "location": "Test room",
            "examine_teacher": self.teacher,
            "category": Activity.ActivityCategory.COURSE,
            "need_apply": False,
            "status": Activity.Status.WAITING,
            "current_participants": 3,
            "capacity": 3,
        }
        fields.update(overrides)
        return Activity.objects.create(**fields)

    @patch("app.course_utils.unlock_achievement")
    def test_stage2_selection_adds_student_to_future_auto_enrol_activity(
            self, _unlock_achievement):
        activity = self.create_activity()

        result = registration_status_change(
            self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 2, result)
        self.assertTrue(CourseParticipant.objects.filter(
            course=self.course,
            person=self.student,
            status=CourseParticipant.Status.SUCCESS,
        ).exists())
        participation = Participation.objects.get(
            activity=activity, person=self.student)
        self.assertEqual(
            participation.status, Participation.AttendStatus.APPLYSUCCESS)
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 4)
        self.assertEqual(activity.capacity, 4)

    @patch("app.course_utils.unlock_achievement")
    def test_stage2_cancellation_removes_future_activity_participation(
            self, _unlock_achievement):
        activity = self.create_activity()
        registration_status_change(self.course.id, self.student, "select")

        result = registration_status_change(
            self.course.id, self.student, "unselect")

        self.assertEqual(result["warn_code"], 2, result)
        self.assertFalse(CourseParticipant.objects.filter(
            course=self.course, person=self.student).exists())
        self.assertFalse(Participation.objects.filter(
            activity=activity, person=self.student).exists())
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 3)
        self.assertEqual(activity.capacity, 3)

    @patch("app.course_utils.unlock_achievement")
    def test_reselection_restores_manually_canceled_course_activity(
            self, _unlock_achievement):
        activity = self.create_activity()
        registration_status_change(self.course.id, self.student, "select")
        activity.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            withdraw_activity_for_person(self.student, activity)

        result = registration_status_change(
            self.course.id, self.student, "unselect")

        self.assertEqual(result["warn_code"], 2, result)
        self.assertFalse(Participation.objects.filter(
            activity=activity, person=self.student).exists())
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 3)
        self.assertEqual(activity.capacity, 3)

        result = registration_status_change(
            self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 2, result)
        participation = Participation.objects.get(
            activity=activity, person=self.student)
        self.assertEqual(
            participation.status, Participation.AttendStatus.APPLYSUCCESS)
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 4)
        self.assertEqual(activity.capacity, 4)

    @patch("app.course_utils.publish_notification")
    @patch("app.course_utils.unlock_achievement")
    def test_stage2_selection_only_notifies_nearest_new_activity(
            self, _unlock_achievement, publish_notification):
        farther_activity = self.create_activity(
            title="Farther activity",
            start=datetime.now() + timedelta(days=2),
            end=datetime.now() + timedelta(days=2, hours=2),
        )
        nearest_activity = self.create_activity(
            title="Nearest activity",
            start=datetime.now() + timedelta(hours=2),
            end=datetime.now() + timedelta(hours=4),
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = registration_status_change(
                self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 2, result)
        notification = Notification.objects.get(
            receiver=self.student.get_user())
        self.assertEqual(
            notification.relate_instance_id, nearest_activity.pk)
        self.assertEqual(
            notification.URL, f"/viewActivity/{nearest_activity.id}")
        self.assertEqual(notification.title, nearest_activity.title)
        self.assertFalse(Notification.objects.filter(
            relate_instance=farther_activity).exists())
        publish_notification.assert_called_once_with(
            notification.id, app=WechatApp.TO_PARTICIPANT)

    @patch("app.course_utils.publish_notification")
    @patch("app.course_utils.unlock_achievement")
    def test_stage2_selection_defers_unpublished_activity_notification(
            self, _unlock_achievement, publish_notification):
        unpublished = self.create_activity(
            title="Unpublished activity",
            status=Activity.Status.UNPUBLISHED,
            start=datetime.now() + timedelta(hours=2),
            end=datetime.now() + timedelta(hours=4),
            publish_time=datetime.now() + timedelta(hours=1),
        )
        published = self.create_activity(
            title="Published activity",
            start=datetime.now() + timedelta(days=1),
            end=datetime.now() + timedelta(days=1, hours=2),
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = registration_status_change(
                self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 2, result)
        self.assertTrue(Participation.objects.filter(
            activity=unpublished, person=self.student).exists())
        notification = Notification.objects.get(
            receiver=self.student.get_user())
        self.assertEqual(notification.relate_instance_id, published.pk)
        publish_notification.assert_called_once_with(
            notification.id, app=WechatApp.TO_PARTICIPANT)

    @patch("app.course_utils.unlock_achievement")
    def test_stage2_selection_does_not_add_ineligible_activities(
            self, _unlock_achievement):
        now = datetime.now()
        self.create_activity(
            title="Requires application",
            need_apply=True,
        )
        self.create_activity(
            title="Already started",
            start=now - timedelta(hours=2),
            end=now - timedelta(hours=1),
            status=Activity.Status.END,
        )
        self.create_activity(
            title="Future but progressing",
            status=Activity.Status.PROGRESSING,
        )
        self.create_activity(
            title="Ordinary activity",
            category=Activity.ActivityCategory.NORMAL,
        )

        result = registration_status_change(
            self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 2, result)
        self.assertFalse(Participation.objects.filter(
            person=self.student).exists())

    @patch("app.course_utils.unlock_achievement")
    def test_existing_participation_is_not_duplicated(
            self, _unlock_achievement):
        activity = self.create_activity()
        Participation.objects.create(
            activity=activity,
            person=self.student,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )

        result = registration_status_change(
            self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 2, result)
        self.assertEqual(Participation.objects.filter(
            activity=activity, person=self.student).count(), 1)
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 3)
        self.assertEqual(activity.capacity, 3)
        _unlock_achievement.assert_called_once_with(
            self.student, "首次报名书院课程")

    @patch("app.course_utils.unlock_achievement")
    def test_full_course_rejects_selection_without_updating_activity(
            self, _unlock_achievement):
        self.course.current_participants = self.course.capacity
        self.course.save(update_fields=["current_participants"])
        activity = self.create_activity()

        result = registration_status_change(
            self.course.id, self.student, "select")

        self.assertEqual(result["warn_code"], 1, result)
        self.assertEqual(result["warn_message"], "选课人数已满！")
        self.assertFalse(CourseParticipant.objects.filter(
            course=self.course, person=self.student).exists())
        self.assertFalse(Participation.objects.filter(
            activity=activity, person=self.student).exists())
        self.course.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(
            self.course.current_participants, self.course.capacity)
        self.assertEqual(activity.current_participants, 3)
        self.assertEqual(activity.capacity, 3)
        _unlock_achievement.assert_not_called()

    def test_accepting_course_org_member_adds_future_activity_participation(
            self):
        self.course.status = Course.Status.SELECT_END
        self.course.save(update_fields=["status"])
        activity = self.create_activity()
        application = ModifyPosition.objects.create(
            person=self.student,
            org=self.organization,
            pos=10,
            apply_type=ModifyPosition.ApplyType.JOIN,
        )

        result = update_pos_application(
            application,
            self.organization,
            self.organization,
            {"post_type": "accept_submit"},
        )

        self.assertEqual(result["warn_code"], 2, result)
        self.assertTrue(Participation.objects.filter(
            activity=activity,
            person=self.student,
            status=Participation.AttendStatus.APPLYSUCCESS,
        ).exists())
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 4)
        self.assertEqual(activity.capacity, 4)

    @patch("app.course_utils.publish_notification")
    def test_accepting_course_org_member_only_notifies_nearest_activity(
            self, publish_notification):
        self.course.status = Course.Status.SELECT_END
        self.course.save(update_fields=["status"])
        farther_activity = self.create_activity(
            title="Farther member activity",
            start=datetime.now() + timedelta(days=2),
            end=datetime.now() + timedelta(days=2, hours=2),
        )
        nearest_activity = self.create_activity(
            title="Nearest member activity",
            start=datetime.now() + timedelta(hours=2),
            end=datetime.now() + timedelta(hours=4),
        )
        application = ModifyPosition.objects.create(
            person=self.student,
            org=self.organization,
            pos=10,
            apply_type=ModifyPosition.ApplyType.JOIN,
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = update_pos_application(
                application,
                self.organization,
                self.organization,
                {"post_type": "accept_submit"},
            )

        self.assertEqual(result["warn_code"], 2, result)
        notification = Notification.objects.get(
            receiver=self.student.get_user())
        self.assertEqual(
            notification.relate_instance_id, nearest_activity.pk)
        self.assertFalse(Notification.objects.filter(
            relate_instance=farther_activity).exists())
        publish_notification.assert_called_once_with(
            notification.id, app=WechatApp.TO_PARTICIPANT)

    def test_accepting_member_during_stage2_does_not_sync_activity(self):
        activity = self.create_activity()
        application = ModifyPosition.objects.create(
            person=self.student,
            org=self.organization,
            pos=10,
            apply_type=ModifyPosition.ApplyType.JOIN,
        )

        result = update_pos_application(
            application,
            self.organization,
            self.organization,
            {"post_type": "accept_submit"},
        )

        self.assertEqual(result["warn_code"], 2, result)
        self.assertFalse(Participation.objects.filter(
            activity=activity, person=self.student).exists())
        self.assertFalse(Notification.objects.filter(
            receiver=self.student.get_user()).exists())
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 3)
        self.assertEqual(activity.capacity, 3)

    def test_stage2_end_creates_position_before_updating_course_status(self):
        CourseParticipant.objects.create(
            course=self.course,
            person=self.student,
            status=CourseParticipant.Status.SUCCESS,
        )

        change_course_status(Course.Status.STAGE2, Course.Status.SELECT_END)

        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.SELECT_END)
        self.assertTrue(Position.objects.activated().filter(
            org=self.organization, person=self.student).exists())
