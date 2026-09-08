"""Real MySQL transaction interleavings for course workflows."""
from threading import Event, Thread

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from app import course_utils, course_views
from app.activity_utils import ActivityException, withdraw_activity_for_person
from app.models import Activity, Course, CourseParticipant, CourseTime, Participation, Position
from app.test.course_fixtures import CourseFixtures


class CourseConcurrencyTests(CourseFixtures, TransactionTestCase):
    """Pause one transaction holding Course until another attempts that lock."""

    def setUp(self):
        super().setUp()
        if connection.vendor != "mysql":
            self.skipTest("Requires MySQL row and foreign-key locks")

    def overlap(self, first, second, table="app_course"):
        locked, attempted = Event(), Event()
        results, errors = {}, []

        def worker(name, operation):
            close_old_connections()
            intercepted = False

            def coordinate(execute, sql, params, many, context):
                nonlocal intercepted
                is_target_lock = "FOR UPDATE" in sql and f"FROM `{table}`" in sql
                if intercepted or not is_target_lock:
                    return execute(sql, params, many, context)
                intercepted = True
                if name == "second":
                    attempted.set()
                    return execute(sql, params, many, context)
                result = execute(sql, params, many, context)
                locked.set()
                if not attempted.wait(10):
                    raise TimeoutError(f"Competing operation did not attempt its {table} lock")
                return result

            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                with connection.execute_wrapper(coordinate):
                    results[name] = operation()
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [Thread(target=worker, args=("first", first), daemon=True),
                   Thread(target=worker, args=("second", second), daemon=True)]
        threads[0].start()
        try:
            self.assertTrue(locked.wait(10), f"First operation did not lock {table}")
            threads[1].start()
        finally:
            for thread in threads:
                if thread.ident is not None:
                    thread.join(20)
            self.assertFalse(any(thread.is_alive() for thread in threads), "Transaction did not finish")
        if errors:
            raise errors[0]
        self.assertTrue(attempted.is_set())
        return results

    def withdraw(self):
        return course_utils.registration_status_change(self.course.pk, self.student, "unselect")

    def assert_withdrawn(self):
        self.assertFalse(CourseParticipant.objects.filter(course=self.course, person=self.student).exists())
        self.assertFalse(Participation.objects.filter(person=self.student).exists())
        for activity in Activity.objects.filter(organization_id=self.organization):
            self.assertEqual(activity.current_participants, 0)
            self.assertEqual(activity.capacity, 0)

    def test_single_creation_overlaps_withdrawal(self):
        self.enroll()
        results = self.overlap(self.single, self.withdraw)
        self.assertEqual(results["second"]["warn_code"], 2)
        self.assert_withdrawn()

    def test_activity_withdrawal_overlaps_course_withdrawal(self):
        activity = self.activity()
        self.enroll()
        self.overlap(
            lambda: withdraw_activity_for_person(self.student, activity),
            self.withdraw, table="app_activity")
        self.assert_withdrawn()

    def test_course_withdrawal_overlaps_activity_withdrawal(self):
        activity = self.activity()
        self.enroll()

        def withdraw_activity():
            with self.assertRaises(ActivityException):
                withdraw_activity_for_person(self.student, activity)

        self.overlap(self.withdraw, withdraw_activity, table="app_activity")
        self.assert_withdrawn()

    def test_weekly_creation_overlaps_withdrawal(self):
        self.enroll()
        results = self.overlap(self.weekly, self.withdraw)
        self.assertEqual(results["second"]["warn_code"], 2)
        self.assert_withdrawn()

    def test_weekly_creation_overlaps_recurring_edit(self):
        activity = self.activity()
        results = self.overlap(self.weekly, lambda: course_views.editCourseActivity(
            self.request(activity), str(activity.pk)))
        self.assertEqual(results["second"].status_code, 200)
        self.course_time.refresh_from_db()
        self.assertEqual(self.course_time.cur_week, 1)
        self.course.refresh_from_db()
        self.assertEqual(self.course.classroom, "New room")

    def test_selection_overlaps_recurring_edit(self):
        activity = self.activity()
        results = self.overlap(self.enroll, lambda: course_views.editCourseActivity(
            self.request(activity), str(activity.pk)))
        self.assertEqual(results["second"].status_code, 200)
        activity.refresh_from_db()
        self.assertEqual(activity.current_participants, 1)

    def test_withdrawal_overlaps_recurring_edit(self):
        activity = self.activity()
        self.enroll()
        results = self.overlap(self.withdraw, lambda: course_views.editCourseActivity(
            self.request(activity), str(activity.pk)))
        self.assertEqual(results["first"]["warn_code"], 2)
        self.assertEqual(results["second"].status_code, 200)
        self.assert_withdrawn()

    def test_recurring_edit_overlaps_cancel_all(self):
        activity = self.activity()
        results = self.overlap(
            lambda: course_views.editCourseActivity(self.request(activity), str(activity.pk)),
            lambda: course_views.showCourseActivity(self.cancellation_request(activity)))
        self.assertEqual(results["first"].status_code, 200)
        self.assertEqual(results["second"].status_code, 200)
        activity.refresh_from_db()
        self.course_time.refresh_from_db()
        self.assertEqual(activity.status, Activity.Status.CANCELED)
        self.assertEqual(self.course_time.end_week, self.course_time.cur_week)

    def test_closing_overlaps_withdrawal(self):
        self.enroll()
        results = self.overlap(lambda: course_utils.change_course_status(
            Course.Status.STAGE2, Course.Status.SELECT_END), self.withdraw)
        self.assertEqual(results["second"]["warn_code"], 1)
        self.assertTrue(Position.objects.activated().filter(
            person=self.student, org=self.organization).exists())
        self.assertTrue(CourseParticipant.objects.filter(
            course=self.course, person=self.student).exists())

    def test_enrollment_overlaps_closing(self):
        self.overlap(self.enroll, lambda: course_utils.change_course_status(
            Course.Status.STAGE2, Course.Status.SELECT_END))
        self.assertTrue(Position.objects.activated().filter(
            person=self.student, org=self.organization).exists())

    def second_course(self):
        return Course.objects.create(
            name="Second course", organization=self.organization,
            type=Course.CourseType.INTELLECTUAL, status=Course.Status.STAGE2,
            capacity=20)

    def test_student_lock_preserves_six_course_limit(self):
        for _ in range(5):
            CourseParticipant.objects.create(
                course=self.second_course(), person=self.student,
                status=CourseParticipant.Status.SUCCESS)
        second_course = self.second_course()
        results = self.overlap(self.enroll, lambda: course_utils.registration_status_change(
            second_course.pk, self.student, "select"), table="app_naturalperson")
        self.assertEqual(results["second"]["warn_code"], 1)
        self.assertEqual(Course.objects.selected(self.student, unfailed=True).count(), 6)

    def test_student_lock_preserves_timetable_check(self):
        second_course = self.second_course()
        CourseTime.objects.create(
            course=second_course, start=self.course_time.start, end=self.course_time.end)
        results = self.overlap(self.enroll, lambda: course_utils.registration_status_change(
            second_course.pk, self.student, "select"), table="app_naturalperson")
        self.assertEqual(results["second"]["warn_code"], 1)
        self.assertEqual(Course.objects.selected(self.student, unfailed=True).count(), 1)
