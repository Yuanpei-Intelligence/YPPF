"""Recurring course edit locking and request protection regressions."""
from django.db import connection
from django.test import TestCase

from app import course_views
from app.models import Activity, Course, CourseTime, Organization, User
from app.test.course_fixtures import CourseFixtures


class CourseActivityLockingTests(CourseFixtures, TestCase):
    def test_add_requires_csrf(self):
        for token in (None, "b" * 32):
            with self.subTest(token=token):
                request = self.request(csrf=False)
                request.COOKIES["csrftoken"] = "a" * 32
                if token is not None:
                    request.META["HTTP_X_CSRFTOKEN"] = token
                with self.assertNumQueries(0):
                    response = course_views.addSingleCourseActivity(request)
                self.assertEqual(response.status_code, 403)

    def test_add_rejects_other_methods(self):
        request = self.request()
        request.method = "PUT"
        self.assertEqual(course_views.addSingleCourseActivity(request).status_code, 405)

    def test_edit_preserves_course_counters_and_renders_form(self):
        activity = self.activity()
        self.enroll()
        response = course_views.editCourseActivity(self.request(activity), str(activity.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "New room")
        self.course.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(self.course.classroom, "New room")
        self.assertEqual(self.course.current_participants, 1)
        self.assertEqual(activity.current_participants, 1)

    def test_edit_requires_csrf_and_rejects_other_methods(self):
        activity = self.activity()
        self.assertEqual(course_views.editCourseActivity(
            self.request(activity, csrf=False), str(activity.pk)).status_code, 403)
        request = self.request(activity)
        request.method = "PUT"
        self.assertEqual(course_views.editCourseActivity(request, str(activity.pk)).status_code, 405)

    def assert_edit_rejected_after_change(self, mutate, expected_status=302):
        activity = self.activity()
        changed = False

        def change_status(execute, sql, params, many, context):
            nonlocal changed
            result = execute(sql, params, many, context)
            if not changed and "FOR UPDATE" in sql and "FROM `app_course`" in sql:
                changed = True
                mutate(activity)
            return result

        with connection.execute_wrapper(change_status):
            response = course_views.editCourseActivity(self.request(activity), str(activity.pk))
        self.assertTrue(changed)
        self.assertEqual(response.status_code, expected_status)
        activity.refresh_from_db()
        self.assertEqual(activity.location, "Room")

    def test_edit_rechecks_activity_after_locking_course(self):
        for changes in (
                {"status": Activity.Status.WAITING},
                {"category": Activity.ActivityCategory.NORMAL},
                {"course_time": None}):
            with self.subTest(changes=changes):
                self.assert_edit_rejected_after_change(
                    lambda activity: Activity.objects.filter(pk=activity.pk).update(**changes))

    def test_edit_rechecks_owner_after_locking_course(self):
        other_user = User.objects.create_user("other_course_org", "Other org", User.Type.ORG)
        other_org = Organization.objects.create(
            organization_id=other_user, oname="Other org", otype=self.organization.otype)
        self.assert_edit_rejected_after_change(
            lambda activity: Activity.objects.filter(pk=activity.pk).update(
                organization_id=other_org), expected_status=403)

    def test_edit_rechecks_course_time_relationship(self):
        other_course = Course.objects.create(
            name="Other course", organization=self.organization,
            type=Course.CourseType.INTELLECTUAL)
        self.assert_edit_rejected_after_change(
            lambda activity: CourseTime.objects.filter(pk=self.course_time.pk).update(
                course=other_course))

    def test_edit_rejects_course_owned_by_another_organization(self):
        activity = self.activity()
        other_user = User.objects.create_user("other_course_org", "Other org", User.Type.ORG)
        other_org = Organization.objects.create(
            organization_id=other_user, oname="Other org", otype=self.organization.otype)
        Course.objects.filter(pk=self.course.pk).update(organization=other_org)
        response = course_views.editCourseActivity(self.request(activity), str(activity.pk))
        self.assertEqual(response.status_code, 403)
        activity.refresh_from_db()
        self.assertEqual(activity.location, "Room")

    def test_standalone_edit_does_not_require_course_time(self):
        activity = self.activity()
        activity.course_time = None
        activity.save(update_fields=["course_time"])
        response = course_views.editCourseActivity(self.request(activity), str(activity.pk))
        self.assertEqual(response.status_code, 200)
        activity.refresh_from_db()
        self.assertEqual(activity.location, "New room")

    def test_cancel_all_requires_csrf(self):
        activity = self.activity()
        response = course_views.showCourseActivity(self.cancellation_request(activity, csrf=False))
        self.assertEqual(response.status_code, 403)
        activity.refresh_from_db()
        self.assertEqual(activity.status, Activity.Status.UNPUBLISHED)

    def test_cancel_all_rejects_standalone_activity(self):
        activity = self.activity()
        activity.course_time = None
        activity.save(update_fields=["course_time"])
        response = course_views.showCourseActivity(self.cancellation_request(activity))
        self.assertEqual(response.status_code, 302)
        activity.refresh_from_db()
        self.assertEqual(activity.status, Activity.Status.UNPUBLISHED)
