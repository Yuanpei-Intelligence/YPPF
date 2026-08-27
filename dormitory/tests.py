from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from app.models import NaturalPerson
from dormitory.management.commands.assign_dormitory import (
    Dormitory as ScoringDormitory,
    Freshman,
)
from dormitory.models import Agreement, Dormitory, DormitoryAssignment
from dormitory.views import (
    DormitoryAgreementViewSet,
    DormitoryAssignmentViewSet,
    DormitoryRoutineQAView,
)
from generic.models import User
from questionnaire.models import (
    AnswerSheet,
    AnswerText,
    Choice,
    Question,
    Survey,
)


class CreateDormitoryQuestionnaire2026Tests(TestCase):
    def test_creation_is_rolled_back_if_a_database_operation_fails(self):
        User.objects.create_user(username="creator", name="Creator", id=1)
        original_create = Question.objects.create

        def fail_on_second_question(**kwargs):
            if kwargs["order"] == 2:
                raise RuntimeError("simulated database operation failure")
            return original_create(**kwargs)

        with patch.object(
            Question.objects, "create", side_effect=fail_on_second_question
        ):
            with self.assertRaises(RuntimeError):
                call_command("create_dormitory_questionnaire_2026")

        self.assertFalse(
            Survey.objects.filter(title="宿舍生活习惯调研-2026").exists()
        )


class DormitoryRoutineQAValidationTests(TestCase):
    def test_session_submission_requires_csrf(self):
        creator = User.objects.create_user(
            username="dormitory_csrf_creator",
            name="Dormitory CSRF Creator",
        )
        student = User.objects.create_user(
            username="dormitory_csrf_student",
            name="Dormitory CSRF Student",
        )
        now = datetime.now()
        survey = Survey.objects.create(
            title="Dormitory CSRF survey",
            creator=creator,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        question = Question.objects.create(
            survey=survey,
            order=1,
            topic="Required text",
            type=Question.Type.TEXT,
            required=True,
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(student)

        with patch.object(
            DormitoryRoutineQAView,
            'get_survey',
            return_value=survey,
        ):
            response = client.post(
                reverse('dormitory-routine-QA'),
                {str(question.order): 'forged response'},
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            AnswerSheet.objects.filter(
                creator=student,
                survey=survey,
            ).exists()
        )

    def test_form_sets_csrf_cookie_and_accepts_valid_token(self):
        creator = User.objects.create_user(
            username="dormitory_csrf_form_creator",
            name="Dormitory CSRF Form Creator",
        )
        student = User.objects.create_user(
            username="dormitory_csrf_form_student",
            name="Dormitory CSRF Form Student",
            utype=User.Type.STUDENT,
            is_newuser=False,
        )
        NaturalPerson.objects.create(student, name='CSRF')
        now = datetime.now()
        survey = Survey.objects.create(
            title="Dormitory CSRF form survey",
            creator=creator,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        question = Question.objects.create(
            survey=survey,
            order=1,
            topic="Required text",
            type=Question.Type.TEXT,
            required=True,
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(student)

        with patch.object(
            DormitoryRoutineQAView,
            'get_survey',
            return_value=survey,
        ):
            form_response = client.get(reverse('dormitory-routine-QA'))
            csrf_token = client.cookies['csrftoken'].value
            submit_response = client.post(
                reverse('dormitory-routine-QA'),
                {
                    str(question.order): 'valid response',
                    'csrfmiddlewaretoken': csrf_token,
                },
            )

        self.assertEqual(form_response.status_code, status.HTTP_200_OK)
        self.assertContains(form_response, 'csrfmiddlewaretoken')
        self.assertRegex(
            form_response.content,
            br'name="csrfmiddlewaretoken" value="[^"]+"',
        )
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        sheet = AnswerSheet.objects.get(creator=student, survey=survey)
        self.assertEqual(sheet.status, AnswerSheet.Status.SUBMITTED)

    def assert_submission_rejection_preserves_input(
        self,
        *,
        survey_status,
        start_time,
        end_time,
        expected_warning,
    ):
        creator = User.objects.create_user(
            username="dormitory_rejection_creator",
            name="Dormitory Rejection Creator",
        )
        student = User.objects.create_user(
            username="dormitory_rejection_student",
            name="Dormitory Rejection Student",
        )
        survey = Survey.objects.create(
            title="Dormitory rejected survey",
            creator=creator,
            status=survey_status,
            start_time=start_time,
            end_time=end_time,
        )
        question = Question.objects.create(
            survey=survey,
            order=1,
            topic="Required text",
            type=Question.Type.TEXT,
            required=True,
        )
        submitted_value = "preserve this response"

        view = DormitoryRoutineQAView()
        view.request = RequestFactory().post(
            "/dormitory/routine-QA/",
            {"1": submitted_value},
        )
        view.request.user = student
        view.get_survey = lambda: survey
        response = object()
        rendered = {}

        def capture_render(**kwargs):
            rendered.update(kwargs)
            return response

        view.render = capture_render

        self.assertIs(view.post(), response)
        self.assertEqual(
            rendered["html_display"],
            {"warn_code": 1, "warn_message": expected_warning},
        )
        rendered_question, _, rendered_value = rendered["survey_iter"][0]
        self.assertEqual(rendered_question, question)
        self.assertEqual(rendered_value, submitted_value)
        self.assertFalse(
            AnswerSheet.objects.filter(survey=survey, creator=student).exists()
        )
        self.assertFalse(AnswerText.objects.filter(question=question).exists())

    def test_invalid_choice_is_rejected_before_answer_sheet_creation(self):
        user = User.objects.create_user(username="student", name="Student")
        survey = Survey.objects.create(
            title="Dormitory survey",
            creator=user,
            start_time="2026-08-08",
            end_time="2026-08-14",
        )
        question = Question.objects.create(
            survey=survey,
            order=1,
            topic="Choice",
            type=Question.Type.SINGLE,
        )
        Choice.objects.create(question=question, order=1, text="Valid")

        view = DormitoryRoutineQAView()
        view.request = RequestFactory().post("/dormitory/routine-QA/", {"1": "2"})
        view.request.user = user
        view.get_survey = lambda: survey
        response = object()
        view.render = lambda **kwargs: response

        self.assertIs(view.post(), response)
        self.assertFalse(AnswerSheet.objects.filter(survey=survey).exists())

    def test_valid_response_is_submitted_and_visible_to_survey_creator(self):
        creator = User.objects.create_user(
            username="dormitory_creator",
            name="Dormitory Creator",
        )
        student = User.objects.create_user(
            username="dormitory_student",
            name="Dormitory Student",
        )
        now = datetime.now()
        survey = Survey.objects.create(
            title="Dormitory published survey",
            creator=creator,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        question = Question.objects.create(
            survey=survey,
            order=1,
            topic="Required text",
            type=Question.Type.TEXT,
            required=True,
        )

        view = DormitoryRoutineQAView()
        view.request = RequestFactory().post(
            "/dormitory/routine-QA/",
            {"1": "valid response"},
        )
        view.request.user = student
        view.get_survey = lambda: survey
        response = object()
        view.render = lambda **kwargs: response

        self.assertIs(view.post(), response)

        sheet = AnswerSheet.objects.get(survey=survey, creator=student)
        self.assertEqual(sheet.status, AnswerSheet.Status.SUBMITTED)
        self.assertEqual(
            AnswerText.objects.get(
                answersheet=sheet,
                question=question,
            ).body,
            "valid response",
        )

        client = APIClient()
        client.force_login(creator)
        result_response = client.get(reverse("answersheet-survey-owner"))

        self.assertEqual(result_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in result_response.data],
            [sheet.pk],
        )

    def test_unpublished_survey_rejection_preserves_entered_values(self):
        now = datetime.now()
        self.assert_submission_rejection_preserves_input(
            survey_status=Survey.Status.ENDED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
            expected_warning="只能提交已发布的问卷！",
        )

    def test_expired_survey_rejection_preserves_entered_values(self):
        now = datetime.now()
        self.assert_submission_rejection_preserves_input(
            survey_status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=1),
            expected_warning="当前不在问卷提交时间内！",
        )

    def test_duplicate_submission_returns_warning_without_new_sheet(self):
        creator = User.objects.create_user(
            username="dormitory_duplicate_creator",
            name="Dormitory Duplicate Creator",
        )
        student = User.objects.create_user(
            username="dormitory_duplicate_student",
            name="Dormitory Duplicate Student",
        )
        now = datetime.now()
        survey = Survey.objects.create(
            title="Dormitory duplicate survey",
            creator=creator,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        question = Question.objects.create(
            survey=survey,
            order=1,
            topic="Required text",
            type=Question.Type.TEXT,
            required=True,
        )
        AnswerSheet.objects.create(creator=student, survey=survey)
        view = DormitoryRoutineQAView()
        view.request = RequestFactory().post(
            "/dormitory/routine-QA/",
            {str(question.order): "duplicate response"},
        )
        view.request.user = student
        view.get_survey = lambda: survey
        response = object()
        rendered = {}

        def capture_render(**kwargs):
            rendered.update(kwargs)
            return response

        view.render = capture_render

        self.assertIs(view.post(), response)
        self.assertEqual(
            rendered["html_display"],
            {"warn_code": 1, "warn_message": "禁止重复创建答卷！"},
        )
        self.assertEqual(
            AnswerSheet.objects.filter(
                creator=student,
                survey=survey,
            ).count(),
            1,
        )

class DormitoryReadApiSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_a = User.objects.create_user(
            username="security_student_a",
            name="Security Student A",
            password="test-password",
            utype=User.Type.STUDENT,
        )
        cls.user_b = User.objects.create_user(
            username="security_student_b",
            name="Security Student B",
            password="test-password",
            utype=User.Type.STUDENT,
        )
        cls.staff_user = User.objects.create_user(
            username="security_staff",
            name="Security Staff",
            password="test-password",
            utype=User.Type.STUDENT,
            is_staff=True,
        )
        cls.inactive_user = User.objects.create_user(
            username="security_inactive",
            name="Security Inactive",
            password="test-password",
            utype=User.Type.STUDENT,
            active=False,
        )
        cls.organization_user = User.objects.create_user(
            username="security_organization",
            name="Security Organization",
            password="test-password",
            utype=User.Type.ORG,
        )
        User.objects.create_user(
            username="zz00000",
            name="Synthetic Official User",
            password="test-password",
        )
        dormitory_a = Dormitory.objects.create(
            id=99001,
            capacity=4,
            gender=Dormitory.Gender.FEMALE,
        )
        dormitory_b = Dormitory.objects.create(
            id=99002,
            capacity=4,
            gender=Dormitory.Gender.MALE,
        )
        cls.assignment_a = DormitoryAssignment.objects.create(
            dormitory=dormitory_a,
            user=cls.user_a,
            bed_id=1,
        )
        cls.assignment_b = DormitoryAssignment.objects.create(
            dormitory=dormitory_b,
            user=cls.user_b,
            bed_id=2,
        )
        cls.agreement_a = Agreement.objects.create(user=cls.user_a)
        cls.agreement_b = Agreement.objects.create(user=cls.user_b)
        cls.staff_assignment = DormitoryAssignment.objects.create(
            dormitory=dormitory_a,
            user=cls.staff_user,
            bed_id=3,
        )
        cls.inactive_assignment = DormitoryAssignment.objects.create(
            dormitory=dormitory_a,
            user=cls.inactive_user,
            bed_id=4,
        )
        cls.organization_assignment = DormitoryAssignment.objects.create(
            dormitory=dormitory_b,
            user=cls.organization_user,
            bed_id=3,
        )
        cls.inactive_assignment_a = DormitoryAssignment.objects.create(
            dormitory=dormitory_b,
            user=cls.user_a,
            bed_id=4,
            active=False,
        )
        cls.staff_agreement = Agreement.objects.create(user=cls.staff_user)
        cls.inactive_agreement = Agreement.objects.create(
            user=cls.inactive_user)
        cls.organization_agreement = Agreement.objects.create(
            user=cls.organization_user)

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_user_cannot_read_dormitory_assignments(self):
        list_response = self.client.get(reverse("dormitoryassignment-list"))
        detail_response = self.client.get(reverse(
            "dormitoryassignment-detail", args=[self.assignment_b.pk]))

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_read_agreements(self):
        list_response = self.client.get(reverse("agreement-query-list"))
        detail_response = self.client.get(reverse(
            "agreement-query-detail", args=[self.agreement_b.pk]))

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_read_legacy_agreement_status(self):
        list_response = self.client.get(
            reverse("agreement-query-fixme-list"))
        detail_response = self.client.get(reverse(
            "agreement-query-fixme-detail", args=[self.agreement_b.pk]))

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(detail_response.status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_authenticated_user_reads_only_own_dormitory_assignment(self):
        self.client.force_login(self.user_a)

        list_response = self.client.get(reverse("dormitoryassignment-list"))
        other_detail_response = self.client.get(reverse(
            "dormitoryassignment-detail", args=[self.assignment_b.pk]))

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [assignment["id"] for assignment in list_response.data],
            [self.assignment_a.pk],
        )
        self.assertEqual(
            set(list_response.data[0]),
            {"id", "dormitory", "bed_id"},
        )
        self.assertEqual(
            other_detail_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_authenticated_user_reads_only_own_agreement(self):
        self.client.force_login(self.user_a)

        list_response = self.client.get(reverse("agreement-query-list"))
        other_detail_response = self.client.get(reverse(
            "agreement-query-detail", args=[self.agreement_b.pk]))

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["id"], self.agreement_a.pk)
        self.assertEqual(
            set(list_response.data[0]),
            {"id", "sign_time"},
        )
        self.assertEqual(
            other_detail_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_jwt_authenticated_user_reads_only_own_records(self):
        token = AccessToken.for_user(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        assignment_response = self.client.get(
            reverse("dormitoryassignment-list")
        )
        agreement_response = self.client.get(reverse("agreement-query-list"))
        legacy_agreement_response = self.client.get(
            reverse("agreement-query-fixme-list")
        )
        other_assignment_response = self.client.get(reverse(
            "dormitoryassignment-detail", args=[self.assignment_b.pk]))
        other_agreement_response = self.client.get(reverse(
            "agreement-query-detail", args=[self.agreement_b.pk]))

        self.assertEqual(assignment_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [assignment["id"] for assignment in assignment_response.data],
            [self.assignment_a.pk],
        )
        self.assertEqual(agreement_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [agreement["id"] for agreement in agreement_response.data],
            [self.agreement_a.pk],
        )
        self.assertEqual(
            legacy_agreement_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            [agreement["id"] for agreement in legacy_agreement_response.data],
            [self.agreement_a.pk],
        )
        self.assertEqual(
            other_assignment_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            other_agreement_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_staff_user_has_no_full_table_bypass(self):
        self.client.force_login(self.staff_user)

        assignment_response = self.client.get(
            reverse("dormitoryassignment-list"))
        agreement_response = self.client.get(reverse("agreement-query-list"))

        self.assertEqual(
            [assignment["id"] for assignment in assignment_response.data],
            [self.staff_assignment.pk],
        )
        self.assertEqual(
            [agreement["id"] for agreement in agreement_response.data],
            [self.staff_agreement.pk],
        )

    def test_inactive_and_organization_users_receive_empty_lists(self):
        cases = [
            (
                self.inactive_user,
                self.inactive_assignment,
                self.inactive_agreement,
            ),
            (
                self.organization_user,
                self.organization_assignment,
                self.organization_agreement,
            ),
        ]
        for user, assignment, agreement in cases:
            self.client.force_login(user)

            assignment_response = self.client.get(
                reverse("dormitoryassignment-list"))
            agreement_response = self.client.get(
                reverse("agreement-query-list"))
            assignment_detail_response = self.client.get(reverse(
                "dormitoryassignment-detail", args=[assignment.pk]))
            agreement_detail_response = self.client.get(reverse(
                "agreement-query-detail", args=[agreement.pk]))

            self.assertEqual(
                assignment_response.status_code,
                status.HTTP_200_OK,
            )
            self.assertEqual(
                agreement_response.status_code,
                status.HTTP_200_OK,
            )
            self.assertEqual(assignment_response.data, [])
            self.assertEqual(agreement_response.data, [])
            self.assertEqual(
                assignment_detail_response.status_code,
                status.HTTP_404_NOT_FOUND,
            )
            self.assertEqual(
                agreement_detail_response.status_code,
                status.HTTP_404_NOT_FOUND,
            )

            self.client.logout()

    def test_legacy_agreement_status_get_does_not_write_database(self):
        self.client.force_login(self.organization_user)
        agreement_count = Agreement.objects.count()

        response = self.client.get(reverse("agreement-query-fixme-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [{"id": 0}])
        self.assertEqual(Agreement.objects.count(), agreement_count)

    def test_sensitive_viewsets_have_no_class_level_querysets(self):
        self.assertNotIn("queryset", DormitoryAssignmentViewSet.__dict__)
        self.assertNotIn("queryset", DormitoryAgreementViewSet.__dict__)

    def test_active_student_reads_only_own_legacy_agreement_status(self):
        self.client.force_login(self.user_a)

        list_response = self.client.get(
            reverse("agreement-query-fixme-list"))
        other_detail_response = self.client.get(reverse(
            "agreement-query-fixme-detail", args=[self.agreement_b.pk]))

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [agreement["id"] for agreement in list_response.data],
            [self.agreement_a.pk],
        )
        self.assertEqual(other_detail_response.status_code,
                         status.HTTP_404_NOT_FOUND)


class DormitoryMajorPreferenceScoringTests(TestCase):
    @staticmethod
    def make_dorm(majors, preferences):
        dorm = ScoringDormitory(101, 4, False)
        for major, preference in zip(majors, preferences):
            dorm.add(Freshman({
                "major": major,
                "major_composition_preference": preference,
                "origin": "省份",
                "personality": 1,
                "olympiad": 0,
                "ac_temp": 26,
                "all_night_ac": 1,
                "wake": 1,
                "sleep": 1,
                "sleep_quality": 1,
                "environment": 0,
                "expectation": 0,
            }))
        return dorm

    def test_major_composition_has_no_room_level_score_without_preferences(self):
        diverse = self.make_dorm([0, 1, 2, 3], ["either"] * 4)
        uneven = self.make_dorm([0, 0, 0, 1], ["either"] * 4)
        same = self.make_dorm([0, 0, 0, 0], ["either"] * 4)

        self.assertEqual(diverse.check_better(), uneven.check_better())
        self.assertEqual(diverse.check_better(), same.check_better())

    def test_similar_preference_rewards_same_major_roommates(self):
        same = self.make_dorm([0, 0, 0, 0], ["similar"] * 4)
        mixed = self.make_dorm([0, 1, 2, 3], ["similar"] * 4)

        self.assertGreater(same.check_better(), mixed.check_better())

    def test_mixed_preference_rewards_cross_discipline_roommates(self):
        same = self.make_dorm([0, 0, 0, 0], ["mixed"] * 4)
        mixed = self.make_dorm([0, 1, 2, 3], ["mixed"] * 4)

        self.assertGreater(mixed.check_better(), same.check_better())

    def test_roommate_personality_preference_rewards_matching_roommates(self):
        matching = self.make_dorm([0, 1, 2, 3], ["either"] * 4)
        mismatching = self.make_dorm([0, 1, 2, 3], ["either"] * 4)
        for student in matching.stu:
            student.data.update(
                personality=2,
                roommate_personality_preference=2,
            )
        for student in mismatching.stu:
            student.data.update(
                personality=0,
                roommate_personality_preference=2,
            )

        # Account for the pre-existing penalty for rooms with >2 introverts.
        self.assertGreater(
            matching.check_better(),
            mismatching.check_better() + 600,
        )

    def test_roommate_expectation_rewards_matching_roommates(self):
        matching = self.make_dorm([0, 1, 2, 3], ["either"] * 4)
        mismatching = self.make_dorm([0, 1, 2, 3], ["either"] * 4)
        for student in matching.stu:
            student.data.update(expectation=1, roommate_expectation=1)
        for student in mismatching.stu:
            student.data.update(expectation=0, roommate_expectation=1)

        self.assertGreater(matching.check_better(), mismatching.check_better())
