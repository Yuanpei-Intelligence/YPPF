"""Shared fixtures for course transaction tests."""
from datetime import datetime, timedelta
from unittest.mock import patch

from django.db import transaction
from django.test import RequestFactory

from app import course_utils, jobs
from app.models import Activity, Course, CourseTime, Notification
from app.test import test_course_late_enrollment as enrollment_tests


class CourseFixtures:
    """Reuse the small enrollment fixture without inheriting its test methods."""
    now = datetime(2026, 9, 6, 12)

    def setUp(self):
        super().setUp()
        enrollment_tests.CourseLateEnrollmentTestCase.setUpTestData.__func__(type(self))
        self.course.photo = "course/test.jpg"
        self.course.save(update_fields=["photo"])
        self.org_user = self.organization.get_user()
        self.org_user.is_newuser = False
        self.org_user.save(update_fields=["is_newuser"])
        self.course_time = CourseTime.objects.create(
            course=self.course, start=self.now + timedelta(days=1),
            end=self.now + timedelta(days=1, hours=2))
        for module in (course_utils, jobs):
            mocked_time = self.enterContext(patch.object(module, "datetime", wraps=datetime))
            mocked_time.now.return_value = self.now
        for target in (
                "app.course_utils.unlock_achievement", "app.course_utils.ScheduleAdder",
                "app.course_utils.remove_job", "app.course_utils.notification_create",
                "app.course_utils.publish_notification", "app.course_utils.bulk_notification_create",
                "app.course_utils.notifyActivity", "app.course_utils.notification_status_change",
                "app.jobs.MultipleAdder", "app.jobs.notification_create"):
            self.enterContext(patch(target))
        config = self.enterContext(patch("app.course_utils.APP_CONFIG"))
        config.audit_teachers = [self.teacher.get_user().username]
        config = self.enterContext(patch("app.jobs.CONFIG"))
        config.course.audit_teachers = [self.teacher.get_user().username]
        config = self.enterContext(patch("app.course_views.APP_CONFIG"))
        config.type_name = self.organization.otype.otype_name
        self.enterContext(patch("app.course_views.utils.get_sidebar_and_navbar", return_value={}))

    def activity(self):
        activity = Activity.objects.create(
            title="Course lesson", organization_id=self.organization,
            examine_teacher=self.teacher, course_time=self.course_time,
            category=Activity.ActivityCategory.COURSE,
            status=Activity.Status.UNPUBLISHED, need_apply=False,
            start=self.course_time.start, end=self.course_time.end,
            publish_time=self.now, location="Room", capacity=0, current_participants=0)
        Notification.objects.create(
            relate_instance=activity, receiver=self.teacher.get_user(),
            sender=self.org_user, typename=Notification.Type.NEEDDO,
            title="Review course activity")
        return activity

    def request(self, activity=None, csrf=True):
        path = f"/editCourseActivity/{activity.pk}" if activity else "/addSingleCourseActivity/"
        request = RequestFactory().post(path, {
            "title": "Edited lesson", "location": "New room",
            "lesson_start": self.course_time.start.strftime("%Y-%m-%d %H:%M"),
            "lesson_end": self.course_time.end.strftime("%Y-%m-%d %H:%M"),
            "publish_day": "instant", "need_apply": "False", "post_type": "modify_all",
        })
        request.user = self.org_user
        if csrf:
            request.COOKIES["csrftoken"] = "a" * 32
            request.META["HTTP_X_CSRFTOKEN"] = "a" * 32
        return request

    def cancellation_request(self, activity, csrf=True):
        request = self.request(activity, csrf=csrf)
        request.POST = request.POST.copy()
        request.POST["cancel-action"] = str(activity.pk)
        request.POST["post_type"] = "cancel_all"
        return request

    def enroll(self):
        result = course_utils.registration_status_change(self.course.pk, self.student, "select")
        self.assertEqual(result["warn_code"], 2, result)

    def weekly(self):
        return jobs.add_week_course_activity(self.course.pk, self.course_time.pk, 0, True)

    def single(self):
        with transaction.atomic():
            return course_utils.create_single_course_activity(self.request())
