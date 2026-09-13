"""Lottery regressions for authoritative reads under the Course lock."""
from django.db import connection
from django.test import TestCase

from app import course_utils
from app.models import Course, CourseParticipant
from app.test.course_fixtures import CourseFixtures


class CourseLockingTests(CourseFixtures, TestCase):
    def prepare_lottery(self):
        self.course.status = Course.Status.DRAWING
        self.course.capacity = 0
        self.course.save(update_fields=["status", "capacity"])
        return CourseParticipant.objects.create(
            course=self.course, person=self.student, status=CourseParticipant.Status.SELECT)

    def change_before_course_lock(self, **changes):
        changed = False

        def wrapper(execute, sql, params, many, context):
            nonlocal changed
            if not changed and "FOR UPDATE" in sql and "FROM `app_course`" in sql:
                changed = True
                Course.objects.filter(pk=self.course.pk).update(**changes)
            return execute(sql, params, many, context)
        return connection.execute_wrapper(wrapper)

    def test_lottery_uses_locked_capacity_and_does_not_repeat(self):
        participant = self.prepare_lottery()
        with self.change_before_course_lock(capacity=1):
            course_utils.draw_lots()
        participant.refresh_from_db()
        self.assertEqual(participant.status, CourseParticipant.Status.SUCCESS)
        notifications = course_utils.bulk_notification_create.call_count
        course_utils.draw_lots()
        self.assertEqual(course_utils.bulk_notification_create.call_count, notifications)
        self.course.refresh_from_db()
        self.assertEqual(self.course.current_participants, 1)

    def test_lottery_skips_course_that_changed_stage(self):
        participant = self.prepare_lottery()
        with self.change_before_course_lock(status=Course.Status.STAGE2):
            course_utils.draw_lots()
        participant.refresh_from_db()
        self.assertEqual(participant.status, CourseParticipant.Status.SELECT)
        course_utils.bulk_notification_create.assert_not_called()
