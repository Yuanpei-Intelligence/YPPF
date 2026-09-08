"""Regression coverage for transaction boundaries and deferred side effects."""
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase

from app import course_utils, course_views
from app.activity_utils import ActivityException, withdraw_activity_for_person
from app.models import Activity, Course, CourseParticipant, Participation
from app.test.course_fixtures import CourseFixtures


class CourseLockBoundaryTests(CourseFixtures, TestCase):
    def test_selection_failure_rolls_back_all_writes_and_callbacks(self):
        activity = self.activity()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with patch.object(course_utils, "unlock_achievement", side_effect=RuntimeError("failure")):
                with self.assertRaises(RuntimeError):
                    self.enroll()
        self.assertEqual(callbacks, [])
        self.course.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(self.course.current_participants, 0)
        self.assertEqual(activity.current_participants, 0)
        self.assertFalse(CourseParticipant.objects.filter(person=self.student).exists())
        self.assertFalse(Participation.objects.filter(person=self.student).exists())

    def test_selection_does_not_overwrite_other_course_fields(self):
        def update_classroom(*args):
            Course.objects.filter(pk=self.course.pk).update(classroom="Changed inside transaction")
            return False, ""

        with patch.object(course_utils, "check_course_time_conflict", side_effect=update_classroom):
            self.enroll()
        self.course.refresh_from_db()
        self.assertEqual(self.course.classroom, "Changed inside transaction")
        self.assertEqual(self.course.current_participants, 1)

    def test_withdraw_uses_locked_activity_and_rejects_duplicate(self):
        activity = self.activity()
        self.enroll()
        # Neither the write nor the caller's response may use a stale count.
        activity.current_participants = 42
        withdraw_activity_for_person(self.student, activity)
        self.assertEqual(activity.current_participants, 0)
        with self.assertRaises(ActivityException):
            withdraw_activity_for_person(self.student, activity)
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 0)

    def test_creation_defers_external_effects(self):
        with self.captureOnCommitCallbacks(execute=True):
            course_utils.create_single_course_activity(self.request())
            course_utils.ScheduleAdder.assert_not_called()
            course_utils.publish_notification.assert_not_called()
        self.assertTrue(course_utils.ScheduleAdder.called)
        course_utils.publish_notification.assert_called_once()

    def test_edit_and_cancel_discard_external_effects_on_rollback(self):
        for operation in (course_utils.modify_course_activity, course_utils.cancel_course_activity):
            with self.subTest(operation=operation.__name__):
                activity = self.activity()
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    with self.assertRaises(RuntimeError):
                        with transaction.atomic():
                            locked = course_views._lock_course_activity(activity, self.organization)
                            operation(self.request(activity), locked)
                            raise RuntimeError("rollback")
                self.assertEqual(callbacks, [])
                course_utils.ScheduleAdder.assert_not_called()
                course_utils.remove_job.assert_not_called()
                course_utils.notifyActivity.assert_not_called()
                activity.refresh_from_db()
                self.assertEqual(activity.status, Activity.Status.UNPUBLISHED)

    def test_edit_and_cancel_run_external_effects_after_commit(self):
        activity = self.activity()
        with self.captureOnCommitCallbacks(execute=True):
            course_utils.modify_course_activity(self.request(activity), activity)
            course_utils.ScheduleAdder.assert_not_called()
        self.assertTrue(course_utils.ScheduleAdder.called)
        with self.captureOnCommitCallbacks(execute=True):
            course_utils.cancel_course_activity(self.request(activity), activity)
            course_utils.notifyActivity.assert_not_called()
            course_utils.remove_job.assert_not_called()
        course_utils.notifyActivity.assert_called_once()
        self.assertTrue(course_utils.remove_job.called)
