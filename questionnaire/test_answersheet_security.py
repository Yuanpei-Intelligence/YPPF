from datetime import datetime, timedelta
from threading import Event, Thread
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import serializers, status
from rest_framework.test import APIClient

from generic.models import User
from questionnaire.models import (
    AnswerSheet,
    AnswerText,
    Choice,
    Question,
    Survey,
)
from questionnaire.utils import create_answersheet, submit_answersheet


class AnswerSheetApiSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.asker = User.objects.create_user(
            username="v10_asker",
            name="V10 Asker",
            password="test-password",
        )
        cls.respondent = User.objects.create_user(
            username="v10_respondent",
            name="V10 Respondent",
            password="test-password",
        )
        cls.unrelated = User.objects.create_user(
            username="v10_unrelated",
            name="V10 Unrelated",
            password="test-password",
        )
        cls.staff = User.objects.create_user(
            username="v10_staff",
            name="V10 Staff",
            password="test-password",
            is_staff=True,
        )
        now = datetime.now()
        cls.survey = Survey.objects.create(
            title="V10 API boundary survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        cls.put_survey = Survey.objects.create(
            title="V10 API PUT boundary survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        cls.submitted_survey = Survey.objects.create(
            title="V10 API submitted boundary survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        cls.draft = AnswerSheet.objects.create(
            survey=cls.survey,
            creator=cls.respondent,
        )
        cls.put_draft = AnswerSheet.objects.create(
            survey=cls.put_survey,
            creator=cls.respondent,
        )
        cls.submitted = AnswerSheet.objects.create(
            survey=cls.submitted_survey,
            creator=cls.respondent,
            status=AnswerSheet.Status.SUBMITTED,
        )

    def setUp(self):
        self.client = APIClient()

    def test_generic_put_and_patch_are_disabled(self):
        self.client.force_login(self.respondent)

        patch_response = self.client.patch(
            reverse("answersheet-detail", args=[self.draft.pk]),
            {
                "survey": self.put_survey.pk,
                "status": AnswerSheet.Status.SUBMITTED,
            },
            format="json",
        )
        put_response = self.client.put(
            reverse("answersheet-detail", args=[self.put_draft.pk]),
            {
                "survey": self.survey.pk,
                "status": AnswerSheet.Status.SUBMITTED,
            },
            format="json",
        )

        self.assertEqual(
            patch_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            put_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.draft.refresh_from_db()
        self.put_draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)
        self.assertEqual(self.put_draft.status, AnswerSheet.Status.DRAFT)

    def test_create_ignores_client_status_and_fixes_creator(self):
        self.client.force_login(self.unrelated)

        response = self.client.post(
            reverse("answersheet-list"),
            {
                "survey": self.survey.pk,
                "creator": self.respondent.pk,
                "status": AnswerSheet.Status.SUBMITTED,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = AnswerSheet.objects.get(pk=response.data["id"])
        self.assertEqual(created.creator, self.unrelated)
        self.assertEqual(created.status, AnswerSheet.Status.DRAFT)

    def test_duplicate_sheet_is_rejected_by_api_and_database(self):
        self.client.force_login(self.respondent)

        response = self.client.post(
            reverse("answersheet-list"),
            {"survey": self.survey.pk},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            AnswerSheet.objects.filter(
                creator=self.respondent,
                survey=self.survey,
            ).count(),
            1,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AnswerSheet.objects.create(
                    creator=self.respondent,
                    survey=self.survey,
                )

    def test_survey_owner_lists_only_submitted_sheets(self):
        self.client.force_login(self.asker)

        response = self.client.get(reverse("answersheet-survey-owner"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in response.data],
            [self.submitted.pk],
        )

    def test_survey_owner_can_retrieve_only_submitted_sheet(self):
        self.client.force_login(self.asker)

        submitted_response = self.client.get(
            reverse("answersheet-detail", args=[self.submitted.pk]))
        draft_response = self.client.get(
            reverse("answersheet-detail", args=[self.draft.pk]))

        self.assertEqual(
            submitted_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            draft_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_staff_has_no_answer_sheet_read_bypass(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("answersheet-detail", args=[self.submitted.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_direct_sheet_list_is_rejected_at_request_level(self):
        self.client.force_login(self.respondent)

        response = self.client.get(reverse("answersheet-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_delete_draft_sheet(self):
        question = Question.objects.create(
            survey=self.survey,
            order=99,
            topic="Draft delete target",
            type=Question.Type.TEXT,
            required=False,
        )
        sheet = self.draft
        answer = AnswerText.objects.create(
            question=question,
            answersheet=sheet,
            body="will be cascaded",
        )
        self.client.force_login(self.respondent)

        response = self.client.delete(
            reverse("answersheet-detail", args=[sheet.pk]))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AnswerSheet.objects.filter(pk=sheet.pk).exists())
        self.assertFalse(AnswerText.objects.filter(pk=answer.pk).exists())

    def test_submitted_sheet_rejects_delete(self):
        question = Question.objects.create(
            survey=self.submitted_survey,
            order=100,
            topic="Submitted delete target",
            type=Question.Type.TEXT,
            required=False,
        )
        answer = AnswerText.objects.create(
            question=question,
            answersheet=self.submitted,
            body="must remain after delete attempt",
        )
        self.client.force_login(self.respondent)

        response = self.client.delete(
            reverse("answersheet-detail", args=[self.submitted.pk]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            AnswerSheet.objects.filter(pk=self.submitted.pk).exists())
        self.assertTrue(AnswerText.objects.filter(pk=answer.pk).exists())
        self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.status, AnswerSheet.Status.SUBMITTED)

    def test_nonowners_cannot_delete_answer_sheets(self):
        targets = (
            ("draft", self.draft),
            ("submitted", self.submitted),
        )
        for actor in (self.asker, self.unrelated, self.staff):
            for name, sheet in targets:
                with self.subTest(actor=actor.username, sheet=name):
                    self.client.force_login(actor)

                    response = self.client.delete(
                        reverse("answersheet-detail", args=[sheet.pk]))

                    self.assertEqual(
                        response.status_code,
                        status.HTTP_404_NOT_FOUND,
                    )
                    self.assertTrue(
                        AnswerSheet.objects.filter(pk=sheet.pk).exists())

    def test_anonymous_user_cannot_delete_sheet(self):
        response = self.client.delete(
            reverse("answersheet-detail", args=[self.draft.pk]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(AnswerSheet.objects.filter(pk=self.draft.pk).exists())

    def test_session_delete_requires_csrf(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        logged_in = csrf_client.login(
            username=self.respondent.username,
            password="test-password",
        )
        self.assertTrue(logged_in)

        response = csrf_client.delete(
            reverse("answersheet-detail", args=[self.draft.pk]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(AnswerSheet.objects.filter(pk=self.draft.pk).exists())


class AnswerSheetSubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.asker = User.objects.create_user(
            username="v10_submit_asker",
            name="V10 Submit Asker",
            password="test-password",
        )
        cls.respondent = User.objects.create_user(
            username="v10_submit_respondent",
            name="V10 Submit Respondent",
            password="test-password",
        )
        cls.unrelated = User.objects.create_user(
            username="v10_submit_unrelated",
            name="V10 Submit Unrelated",
            password="test-password",
        )
        cls.staff = User.objects.create_user(
            username="v10_submit_staff",
            name="V10 Submit Staff",
            password="test-password",
            is_staff=True,
        )
        cls.organization_account = User.objects.create_user(
            username="v10_submit_org",
            name="V10 Submit Organization",
            password="test-password",
            utype=User.Type.ORG,
        )
        cls.now = datetime.now()
        cls.survey = Survey.objects.create(
            title="V10 submit survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=cls.now - timedelta(days=1),
            end_time=cls.now + timedelta(days=1),
        )
        cls.required_question = Question.objects.create(
            survey=cls.survey,
            order=1,
            topic="Required text",
            type=Question.Type.TEXT,
            required=True,
        )
        cls.choice_question = Question.objects.create(
            survey=cls.survey,
            order=2,
            topic="Optional choice",
            type=Question.Type.SINGLE,
            required=False,
        )
        Choice.objects.create(
            question=cls.choice_question,
            order=1,
            text="Valid",
        )
        cls.draft = AnswerSheet.objects.create(
            survey=cls.survey,
            creator=cls.respondent,
        )
        cls.required_answer = AnswerText.objects.create(
            question=cls.required_question,
            answersheet=cls.draft,
            body="complete",
        )
        cls.submitted_survey = Survey.objects.create(
            title="V10 already submitted survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=cls.now - timedelta(days=1),
            end_time=cls.now + timedelta(days=1),
        )
        cls.submitted_question = Question.objects.create(
            survey=cls.submitted_survey,
            order=1,
            topic="Already submitted required text",
            type=Question.Type.TEXT,
            required=True,
        )
        cls.submitted = AnswerSheet.objects.create(
            survey=cls.submitted_survey,
            creator=cls.respondent,
            status=AnswerSheet.Status.SUBMITTED,
        )
        AnswerText.objects.create(
            question=cls.submitted_question,
            answersheet=cls.submitted,
            body="already submitted",
        )

    def setUp(self):
        self.client = APIClient()

    def _submit(self, sheet=None):
        target = self.draft if sheet is None else sheet
        return self.client.post(
            f"/questionnaire/answersheet/{target.pk}/submit/",
            {},
            format="json",
        )

    def _new_draft(self, survey=None):
        target_survey = self.survey if survey is None else survey
        return AnswerSheet.objects.create(
            survey=target_survey,
            creator=self.respondent,
        )

    def test_owner_submits_complete_draft(self):
        self.client.force_login(self.respondent)

        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.SUBMITTED)
        self.assertEqual(response.data["status"], AnswerSheet.Status.SUBMITTED)

    def test_nonowners_cannot_submit_respondent_draft(self):
        for actor in (
            self.asker,
            self.unrelated,
            self.staff,
            self.organization_account,
        ):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)

                response = self._submit()

                self.assertEqual(
                    response.status_code,
                    status.HTTP_404_NOT_FOUND,
                )
                self.draft.refresh_from_db()
                self.assertEqual(
                    self.draft.status,
                    AnswerSheet.Status.DRAFT,
                )

    def test_anonymous_user_cannot_submit(self):
        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)

    def test_session_submit_requires_csrf(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        logged_in = csrf_client.login(
            username=self.respondent.username,
            password="test-password",
        )
        self.assertTrue(logged_in)

        response = csrf_client.post(
            f"/questionnaire/answersheet/{self.draft.pk}/submit/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)

    def test_repeated_submit_is_rejected(self):
        self.client.force_login(self.respondent)

        response = self._submit(self.submitted)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.submitted.refresh_from_db()
        self.assertEqual(
            self.submitted.status,
            AnswerSheet.Status.SUBMITTED,
        )

    def test_missing_required_answer_does_not_submit(self):
        self.required_answer.delete()
        self.client.force_login(self.respondent)

        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)
        self.assertFalse(
            AnswerText.objects.filter(answersheet=self.draft).exists())

    def test_survey_state_and_time_window_are_enforced(self):
        cases = [
            (
                "not-published",
                Survey.Status.REVIEWING,
                self.now - timedelta(days=1),
                self.now + timedelta(days=1),
            ),
            (
                "not-started",
                Survey.Status.PUBLISHED,
                self.now + timedelta(days=1),
                self.now + timedelta(days=2),
            ),
            (
                "expired",
                Survey.Status.PUBLISHED,
                self.now - timedelta(days=2),
                self.now - timedelta(days=1),
            ),
        ]
        self.client.force_login(self.respondent)
        for name, survey_status, start_time, end_time in cases:
            with self.subTest(case=name):
                survey = Survey.objects.create(
                    title=f"V10 submit {name}",
                    creator=self.asker,
                    status=survey_status,
                    start_time=start_time,
                    end_time=end_time,
                )
                question = Question.objects.create(
                    survey=survey,
                    order=1,
                    topic=f"Required {name}",
                    type=Question.Type.TEXT,
                    required=True,
                )
                sheet = self._new_draft(survey)
                AnswerText.objects.create(
                    question=question,
                    answersheet=sheet,
                    body="complete",
                )

                response = self._submit(sheet)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                sheet.refresh_from_db()
                self.assertEqual(sheet.status, AnswerSheet.Status.DRAFT)

    def test_duplicate_answers_do_not_submit(self):
        AnswerText.objects.create(
            question=self.required_question,
            answersheet=self.draft,
            body="duplicate",
        )
        self.client.force_login(self.respondent)

        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)
        self.assertEqual(
            AnswerText.objects.filter(answersheet=self.draft).count(),
            2,
        )

    def test_cross_survey_answer_does_not_submit(self):
        other_survey = Survey.objects.create(
            title="V10 other survey",
            creator=self.asker,
            status=Survey.Status.PUBLISHED,
            start_time=self.now - timedelta(days=1),
            end_time=self.now + timedelta(days=1),
        )
        other_question = Question.objects.create(
            survey=other_survey,
            order=1,
            topic="Other question",
            type=Question.Type.TEXT,
        )
        AnswerText.objects.create(
            question=other_question,
            answersheet=self.draft,
            body="cross survey",
        )
        self.client.force_login(self.respondent)

        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)

    def test_empty_stored_answer_does_not_submit(self):
        self.required_answer.body = ""
        self.required_answer.save(update_fields=["body"])
        self.client.force_login(self.respondent)

        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.draft.refresh_from_db()
        self.required_answer.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)
        self.assertEqual(self.required_answer.body, "")

    def test_invalid_choice_answer_does_not_submit(self):
        AnswerText.objects.create(
            question=self.choice_question,
            answersheet=self.draft,
            body="99",
        )
        self.client.force_login(self.respondent)

        response = self._submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AnswerSheet.Status.DRAFT)

    def test_submit_reuses_prefetched_choices(self):
        second_choice_question = Question.objects.create(
            survey=self.survey,
            order=3,
            topic="Second optional choice",
            type=Question.Type.SINGLE,
            required=False,
        )
        Choice.objects.create(
            question=second_choice_question,
            order=1,
            text="Second valid choice",
        )
        AnswerText.objects.create(
            question=self.choice_question,
            answersheet=self.draft,
            body="1",
        )
        AnswerText.objects.create(
            question=second_choice_question,
            answersheet=self.draft,
            body="1",
        )

        with CaptureQueriesContext(connection) as queries:
            submit_answersheet(self.draft.pk, self.respondent, now=self.now)

        choice_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "questionnaire_choice" in query["sql"].lower()
        ]
        self.assertEqual(len(choice_queries), 1, choice_queries)


class AnswerTextSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.asker = User.objects.create_user(
            username="v10_text_asker",
            name="V10 Text Asker",
            password="test-password",
        )
        cls.respondent = User.objects.create_user(
            username="v10_text_respondent",
            name="V10 Text Respondent",
            password="test-password",
        )
        cls.unrelated = User.objects.create_user(
            username="v10_text_unrelated",
            name="V10 Text Unrelated",
            password="test-password",
        )
        cls.staff = User.objects.create_user(
            username="v10_text_staff",
            name="V10 Text Staff",
            password="test-password",
            is_staff=True,
        )
        now = datetime.now()
        cls.survey = Survey.objects.create(
            title="V10 answer text survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        cls.primary_question = Question.objects.create(
            survey=cls.survey,
            order=1,
            topic="Primary text",
            type=Question.Type.TEXT,
        )
        cls.optional_question = Question.objects.create(
            survey=cls.survey,
            order=2,
            topic="Optional text",
            type=Question.Type.TEXT,
            required=False,
        )
        cls.submitted_survey = Survey.objects.create(
            title="V10 submitted answer text survey",
            creator=cls.asker,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        cls.submitted_primary_question = Question.objects.create(
            survey=cls.submitted_survey,
            order=1,
            topic="Submitted primary text",
            type=Question.Type.TEXT,
        )
        cls.submitted_optional_question = Question.objects.create(
            survey=cls.submitted_survey,
            order=2,
            topic="Submitted optional text",
            type=Question.Type.TEXT,
            required=False,
        )
        cls.draft = AnswerSheet.objects.create(
            survey=cls.survey,
            creator=cls.respondent,
        )
        cls.submitted = AnswerSheet.objects.create(
            survey=cls.submitted_survey,
            creator=cls.respondent,
            status=AnswerSheet.Status.SUBMITTED,
        )
        cls.draft_answer = AnswerText.objects.create(
            question=cls.primary_question,
            answersheet=cls.draft,
            body="draft body",
        )
        cls.submitted_answer = AnswerText.objects.create(
            question=cls.submitted_primary_question,
            answersheet=cls.submitted,
            body="submitted body",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.raise_request_exception = False

    def test_owner_can_create_sparse_update_and_delete_answer_in_draft(self):
        self.client.force_login(self.respondent)

        create_response = self.client.post(
            reverse("answertext-list"),
            {
                "question": self.optional_question.pk,
                "answersheet": self.draft.pk,
                "body": "optional body",
            },
            format="json",
        )
        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )
        answer_id = create_response.data["id"]

        update_response = self.client.patch(
            reverse("answertext-detail", args=[answer_id]),
            {"body": "updated body"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            AnswerText.objects.get(pk=answer_id).body,
            "updated body",
        )

        delete_response = self.client.delete(
            reverse("answertext-detail", args=[answer_id]))
        self.assertEqual(
            delete_response.status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertFalse(AnswerText.objects.filter(pk=answer_id).exists())

    def test_submitted_sheet_rejects_answer_create(self):
        self.client.force_login(self.respondent)

        response = self.client.post(
            reverse("answertext-list"),
            {
                "question": self.submitted_optional_question.pk,
                "answersheet": self.submitted.pk,
                "body": "late answer",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(AnswerText.objects.filter(
            question=self.submitted_optional_question,
            answersheet=self.submitted,
        ).exists())

    def test_submitted_sheet_rejects_answer_update(self):
        self.client.force_login(self.respondent)

        response = self.client.patch(
            reverse(
                "answertext-detail",
                args=[self.submitted_answer.pk],
            ),
            {"body": "changed after submit"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.submitted_answer.refresh_from_db()
        self.assertEqual(self.submitted_answer.body, "submitted body")

    def test_submitted_sheet_rejects_answer_delete(self):
        self.client.force_login(self.respondent)

        response = self.client.delete(reverse(
            "answertext-detail",
            args=[self.submitted_answer.pk],
        ))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(AnswerText.objects.filter(
            pk=self.submitted_answer.pk).exists())

    def test_nonowners_cannot_create_draft_answer(self):
        for actor in (self.asker, self.unrelated, self.staff):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)

                response = self.client.post(
                    reverse("answertext-list"),
                    {
                        "question": self.optional_question.pk,
                        "answersheet": self.draft.pk,
                        "body": f"created by {actor.username}",
                    },
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                )
                self.assertFalse(AnswerText.objects.filter(
                    question=self.optional_question,
                    answersheet=self.draft,
                ).exists())

    def test_nonowners_cannot_update_draft_answer(self):
        for actor in (self.asker, self.unrelated, self.staff):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)

                response = self.client.patch(
                    reverse(
                        "answertext-detail",
                        args=[self.draft_answer.pk],
                    ),
                    {"body": f"changed by {actor.username}"},
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_404_NOT_FOUND,
                )
                self.draft_answer.refresh_from_db()
                self.assertEqual(self.draft_answer.body, "draft body")

    def test_nonowners_cannot_delete_draft_answer(self):
        for index, actor in enumerate(
            (self.asker, self.unrelated, self.staff),
            start=10,
        ):
            with self.subTest(actor=actor.username):
                question = Question.objects.create(
                    survey=self.survey,
                    order=index,
                    topic=f"Delete target {index}",
                    type=Question.Type.TEXT,
                )
                answer = AnswerText.objects.create(
                    question=question,
                    answersheet=self.draft,
                    body="must remain",
                )
                self.client.force_login(actor)

                response = self.client.delete(reverse(
                    "answertext-detail",
                    args=[answer.pk],
                ))

                self.assertEqual(
                    response.status_code,
                    status.HTTP_404_NOT_FOUND,
                )
                self.assertTrue(
                    AnswerText.objects.filter(pk=answer.pk).exists())

    def test_survey_owner_sees_only_submitted_answers(self):
        self.client.force_login(self.asker)

        response = self.client.get(reverse("answertext-survey-owner"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in response.data],
            [self.submitted_answer.pk],
        )

    def test_survey_owner_can_retrieve_only_submitted_answer(self):
        self.client.force_login(self.asker)

        submitted_response = self.client.get(reverse(
            "answertext-detail",
            args=[self.submitted_answer.pk],
        ))
        draft_response = self.client.get(reverse(
            "answertext-detail",
            args=[self.draft_answer.pk],
        ))

        self.assertEqual(
            submitted_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            draft_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_staff_has_no_answer_text_read_bypass(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse(
            "answertext-detail",
            args=[self.submitted_answer.pk],
        ))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_direct_answer_list_is_rejected_at_request_level(self):
        self.client.force_login(self.respondent)

        response = self.client.get(reverse("answertext-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_answer_owner_reads_own_draft_and_submitted_answers(self):
        self.client.force_login(self.respondent)

        response = self.client.get(reverse("answertext-answer-owner"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {row["id"] for row in response.data},
            {self.draft_answer.pk, self.submitted_answer.pk},
        )


class AnswerSheetConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.asker = User.objects.create_user(
            username="v10_race_asker",
            name="V10 Race Asker",
        )
        self.respondent = User.objects.create_user(
            username="v10_race_respondent",
            name="V10 Race Respondent",
        )
        now = datetime.now()
        self.survey = Survey.objects.create(
            title="V10 race survey",
            creator=self.asker,
            status=Survey.Status.PUBLISHED,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )
        self.required_question = Question.objects.create(
            survey=self.survey,
            order=1,
            topic="Required answer",
            type=Question.Type.TEXT,
            required=True,
        )
        self.optional_question = Question.objects.create(
            survey=self.survey,
            order=2,
            topic="Optional answer",
            type=Question.Type.TEXT,
            required=False,
        )
        self.sheet = AnswerSheet.objects.create(
            survey=self.survey,
            creator=self.respondent,
        )
        self.required_answer = AnswerText.objects.create(
            question=self.required_question,
            answersheet=self.sheet,
            body="committed before submit",
        )

    @staticmethod
    def _is_sheet_lock(sql):
        normalized = " ".join(sql.upper().split())
        return (
            "FOR UPDATE" in normalized
            and "QUESTIONNAIRE_ANSWERSHEET" in normalized
        )

    @staticmethod
    def _is_unlocked_sheet_read(sql):
        normalized = " ".join(sql.upper().split())
        return (
            normalized.startswith("SELECT")
            and "QUESTIONNAIRE_ANSWERSHEET" in normalized
            and "FOR UPDATE" not in normalized
        )

    @staticmethod
    def _is_unlocked_answer_read(sql):
        normalized = " ".join(sql.upper().split())
        return (
            normalized.startswith("SELECT")
            and "QUESTIONNAIRE_ANSWERTEXT" in normalized
            and "FOR UPDATE" not in normalized
        )

    def _start_paused_answer_patch(self, data):
        answer_read = Event()
        allow_patch = Event()
        results = {}
        errors = []
        paused = {"value": False}

        def pause_after_initial_read(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if (
                not paused["value"]
                and self._is_unlocked_answer_read(sql)
            ):
                paused["value"] = True
                answer_read.set()
                if not allow_patch.wait(10):
                    raise TimeoutError("answer PATCH was not released by test")
            return result

        def patch_worker():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            try:
                with connection.execute_wrapper(pause_after_initial_read):
                    response = client.patch(
                        reverse(
                            "answertext-detail",
                            args=[self.required_answer.pk],
                        ),
                        data,
                        format="json",
                    )
                results["status"] = response.status_code
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        thread = Thread(target=patch_worker)
        thread.start()
        if not answer_read.wait(10):
            allow_patch.set()
            thread.join(10)
            self.fail("PATCH did not perform its initial unlocked answer read")
        return thread, allow_patch, results, errors

    def _finish_paused_request(self, thread, release, results, errors):
        release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "paused request did not finish")
        if errors:
            raise errors[0]
        return results["status"]

    def _race_submit_against_mutation(self, method, path, data=None):
        submit_has_lock = Event()
        allow_submit = Event()
        mutation_attempted_lock = Event()
        mutation_done = Event()
        results = {}
        errors = []
        submit_paused = {"value": False}
        mutation_signaled = {"value": False}

        def pause_submit_after_lock(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if (
                not submit_paused["value"]
                and self._is_sheet_lock(sql)
            ):
                submit_paused["value"] = True
                submit_has_lock.set()
                if not allow_submit.wait(10):
                    raise TimeoutError("submit lock was not released by test")
            return result

        def signal_mutation_lock_attempt(execute, sql, params, many, context):
            if (
                not mutation_signaled["value"]
                and self._is_sheet_lock(sql)
            ):
                mutation_signaled["value"] = True
                mutation_attempted_lock.set()
            return execute(sql, params, many, context)

        def submit_worker():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            try:
                with connection.execute_wrapper(pause_submit_after_lock):
                    response = client.post(
                        reverse("answersheet-submit", args=[self.sheet.pk]),
                        {},
                        format="json",
                    )
                results["submit"] = response.status_code
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        def mutation_worker():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            try:
                with connection.execute_wrapper(signal_mutation_lock_attempt):
                    request_method = getattr(client, method)
                    response = request_method(path, data or {}, format="json")
                results["mutation"] = response.status_code
            except BaseException as exc:
                errors.append(exc)
            finally:
                mutation_done.set()
                close_old_connections()

        submit_thread = Thread(target=submit_worker)
        mutation_thread = Thread(target=mutation_worker)
        submit_thread.start()
        mutation_started = False
        try:
            self.assertTrue(
                submit_has_lock.wait(10),
                "submit did not acquire the answer-sheet row lock",
            )
            mutation_thread.start()
            mutation_started = True
            self.assertTrue(
                mutation_attempted_lock.wait(10),
                "answer mutation did not attempt the same row lock",
            )
            self.assertFalse(
                mutation_done.wait(0.25),
                "answer mutation completed while submit held the row lock",
            )
        finally:
            allow_submit.set()
            submit_thread.join(10)
            if mutation_started:
                mutation_thread.join(10)

        self.assertFalse(submit_thread.is_alive(), "submit thread did not finish")
        self.assertFalse(
            mutation_thread.is_alive(),
            "answer mutation thread did not finish",
        )
        if errors:
            raise errors[0]
        self.assertEqual(results["submit"], status.HTTP_200_OK)
        self.assertEqual(results["mutation"], status.HTTP_400_BAD_REQUEST)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, AnswerSheet.Status.SUBMITTED)

    def test_submit_wins_race_against_answer_create(self):
        self._race_submit_against_mutation(
            "post",
            reverse("answertext-list"),
            {
                "question": self.optional_question.pk,
                "answersheet": self.sheet.pk,
                "body": "must be rejected",
            },
        )

        self.assertFalse(AnswerText.objects.filter(
            answersheet=self.sheet,
            question=self.optional_question,
        ).exists())

    def test_submit_wins_race_against_answer_update(self):
        self._race_submit_against_mutation(
            "patch",
            reverse("answertext-detail", args=[self.required_answer.pk]),
            {"body": "must be rejected"},
        )

        self.required_answer.refresh_from_db()
        self.assertEqual(
            self.required_answer.body,
            "committed before submit",
        )

    def test_submit_wins_race_against_answer_delete(self):
        self._race_submit_against_mutation(
            "delete",
            reverse("answertext-detail", args=[self.required_answer.pk]),
        )

        self.assertTrue(
            AnswerText.objects.filter(pk=self.required_answer.pk).exists())

    def test_submit_wins_race_against_sheet_delete(self):
        self._race_submit_against_mutation(
            "delete",
            reverse("answersheet-detail", args=[self.sheet.pk]),
        )

        self.assertTrue(AnswerSheet.objects.filter(pk=self.sheet.pk).exists())
        self.assertTrue(
            AnswerText.objects.filter(pk=self.required_answer.pk).exists())
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, AnswerSheet.Status.SUBMITTED)

    def test_concurrent_submit_only_one_succeeds(self):
        self._race_submit_against_mutation(
            "post",
            reverse("answersheet-submit", args=[self.sheet.pk]),
        )

    def test_waiting_submit_captures_default_time_after_sheet_lock(self):
        deadline = datetime(2030, 8, 26, 12, 0, 0)
        self.survey.start_time = deadline - timedelta(days=1)
        self.survey.end_time = deadline
        self.survey.save(update_fields=['start_time', 'end_time'])
        lock_attempted = Event()
        deadline_passed = Event()
        now_called = Event()
        results = {}
        errors = []
        lock_signaled = {"value": False}

        def fake_now():
            now_called.set()
            if deadline_passed.is_set():
                return deadline + timedelta(seconds=1)
            return deadline - timedelta(seconds=1)

        def signal_sheet_lock(execute, sql, params, many, context):
            if not lock_signaled["value"] and self._is_sheet_lock(sql):
                lock_signaled["value"] = True
                lock_attempted.set()
            return execute(sql, params, many, context)

        def submit_worker():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            try:
                with patch('questionnaire.utils.datetime') as mock_datetime:
                    mock_datetime.now.side_effect = fake_now
                    with connection.execute_wrapper(signal_sheet_lock):
                        response = client.post(
                            reverse(
                                "answersheet-submit",
                                args=[self.sheet.pk],
                            ),
                            {},
                            format="json",
                        )
                results["status"] = response.status_code
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        lock_observed = False
        called_before_lock = False
        with transaction.atomic():
            AnswerSheet.objects.select_for_update().get(pk=self.sheet.pk)
            submit_thread = Thread(target=submit_worker)
            submit_thread.start()
            try:
                lock_observed = lock_attempted.wait(10)
                called_before_lock = now_called.is_set()
            finally:
                deadline_passed.set()

        submit_thread.join(10)
        self.assertTrue(
            lock_observed,
            "submit did not attempt the answer-sheet row lock",
        )
        self.assertFalse(submit_thread.is_alive())
        if errors:
            raise errors[0]
        self.assertFalse(
            called_before_lock,
            "submit captured the deadline timestamp before acquiring the lock",
        )
        self.assertEqual(results["status"], status.HTTP_400_BAD_REQUEST)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, AnswerSheet.Status.DRAFT)

    def test_submit_reloads_survey_state_after_answer_validation(self):
        answer_read = Event()
        allow_submit = Event()
        results = {}
        errors = []
        paused = {"value": False}

        def pause_after_answer_read(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if not paused["value"] and self._is_unlocked_answer_read(sql):
                paused["value"] = True
                answer_read.set()
                if not allow_submit.wait(10):
                    raise TimeoutError("submit was not released by test")
            return result

        def submit_worker():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            try:
                with connection.execute_wrapper(pause_after_answer_read):
                    response = client.post(
                        reverse(
                            "answersheet-submit",
                            args=[self.sheet.pk],
                        ),
                        {},
                        format="json",
                    )
                results["status"] = response.status_code
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        submit_thread = Thread(target=submit_worker)
        submit_thread.start()
        try:
            self.assertTrue(
                answer_read.wait(10),
                "submit did not read answers before the survey state check",
            )
            Survey.objects.filter(pk=self.survey.pk).update(
                status=Survey.Status.ENDED,
            )
        finally:
            allow_submit.set()
            submit_thread.join(10)

        self.assertFalse(submit_thread.is_alive())
        if errors:
            raise errors[0]
        self.assertEqual(results["status"], status.HTTP_400_BAD_REQUEST)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, AnswerSheet.Status.DRAFT)

    def test_empty_patch_after_update_preserves_committed_body(self):
        thread, release, results, errors = self._start_paused_answer_patch({})
        client = APIClient()
        client.force_authenticate(user=self.respondent)

        update_response = client.patch(
            reverse(
                "answertext-detail",
                args=[self.required_answer.pk],
            ),
            {"body": "new committed body"},
            format="json",
        )
        paused_status = self._finish_paused_request(
            thread,
            release,
            results,
            errors,
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(paused_status, status.HTTP_200_OK)
        self.required_answer.refresh_from_db()
        self.assertEqual(self.required_answer.body, "new committed body")

    def test_deleted_answer_is_not_resurrected_by_waiting_patch(self):
        thread, release, results, errors = self._start_paused_answer_patch(
            {"body": "must not be resurrected"},
        )
        client = APIClient()
        client.force_authenticate(user=self.respondent)

        delete_response = client.delete(reverse(
            "answertext-detail",
            args=[self.required_answer.pk],
        ))
        paused_status = self._finish_paused_request(
            thread,
            release,
            results,
            errors,
        )

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(paused_status, status.HTTP_404_NOT_FOUND)
        self.assertFalse(
            AnswerText.objects.filter(pk=self.required_answer.pk).exists())

    def test_deleted_sheet_returns_404_to_waiting_answer_patch(self):
        thread, release, results, errors = self._start_paused_answer_patch(
            {"body": "must not survive sheet deletion"},
        )
        client = APIClient()
        client.force_authenticate(user=self.respondent)

        delete_response = client.delete(reverse(
            "answersheet-detail",
            args=[self.sheet.pk],
        ))
        paused_status = self._finish_paused_request(
            thread,
            release,
            results,
            errors,
        )

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(paused_status, status.HTTP_404_NOT_FOUND)
        self.assertFalse(AnswerSheet.objects.filter(pk=self.sheet.pk).exists())
        self.assertFalse(
            AnswerText.objects.filter(pk=self.required_answer.pk).exists())

    def _start_paused_sheet_create(self, actor, result_key, results, errors):
        created = Event()
        release = Event()

        def create_worker():
            close_old_connections()
            try:
                with transaction.atomic():
                    sheet = create_answersheet(self.survey.pk, actor)
                    results[result_key] = sheet.pk
                    created.set()
                    if not release.wait(10):
                        raise TimeoutError(
                            "sheet create was not released by test")
            except BaseException as exc:
                errors.append(exc)
                created.set()
            finally:
                close_old_connections()

        thread = Thread(target=create_worker)
        thread.start()
        if not created.wait(10):
            release.set()
            thread.join(10)
            self.fail("sheet create did not reach its outer transaction")
        if errors:
            release.set()
            thread.join(10)
            raise errors[0]
        return thread, release

    def test_different_respondents_create_without_survey_lock(self):
        first_respondent = User.objects.create_user(
            username="v10_race_create_first",
            name="V10 Race Create First",
        )
        second_respondent = User.objects.create_user(
            username="v10_race_create_second",
            name="V10 Race Create Second",
        )
        results = {}
        errors = []
        first_thread, release_first = self._start_paused_sheet_create(
            first_respondent,
            "first",
            results,
            errors,
        )

        second_done = Event()

        def create_second():
            close_old_connections()
            try:
                results["second"] = create_answersheet(
                    self.survey.pk,
                    second_respondent,
                ).pk
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()
                close_old_connections()

        second_thread = Thread(target=create_second)
        second_thread.start()
        try:
            completed_without_release = second_done.wait(5)
        finally:
            release_first.set()
            first_thread.join(10)
            second_thread.join(10)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        if errors:
            raise errors[0]
        self.assertTrue(
            completed_without_release,
            "an unrelated respondent waited for the first transaction",
        )
        self.assertEqual(set(results), {"first", "second"})
        self.assertEqual(
            AnswerSheet.objects.filter(
                creator__in=[first_respondent, second_respondent],
                survey=self.survey,
            ).count(),
            2,
        )

    def test_same_respondent_concurrent_create_is_rejected(self):
        respondent = User.objects.create_user(
            username="v10_race_create_same",
            name="V10 Race Create Same",
        )
        results = {}
        errors = []
        first_thread, release_first = self._start_paused_sheet_create(
            respondent,
            "first",
            results,
            errors,
        )
        second_done = Event()

        def create_second():
            close_old_connections()
            try:
                create_answersheet(self.survey.pk, respondent)
                results["second"] = "created"
            except serializers.ValidationError:
                results["second"] = "rejected"
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()
                close_old_connections()

        second_thread = Thread(target=create_second)
        second_thread.start()
        try:
            completed_before_commit = second_done.wait(0.25)
        finally:
            release_first.set()
            first_thread.join(10)
            second_thread.join(10)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        if errors:
            raise errors[0]
        self.assertFalse(
            completed_before_commit,
            "duplicate create did not wait for the unique-key decision",
        )
        self.assertEqual(results["second"], "rejected")
        self.assertEqual(
            AnswerSheet.objects.filter(
                creator=respondent,
                survey=self.survey,
            ).count(),
            1,
        )

    def test_sheet_delete_wins_race_against_submit(self):
        submit_read_sheet = Event()
        allow_submit_to_lock = Event()
        submit_paused = {"value": False}
        results = {}
        errors = []

        def pause_submit_after_initial_read(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if (
                not submit_paused["value"]
                and self._is_unlocked_sheet_read(sql)
            ):
                submit_paused["value"] = True
                submit_read_sheet.set()
                if not allow_submit_to_lock.wait(10):
                    raise TimeoutError("submit read was not released by test")
            return result

        def submit_worker():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            try:
                with connection.execute_wrapper(pause_submit_after_initial_read):
                    response = client.post(
                        reverse("answersheet-submit", args=[self.sheet.pk]),
                        {},
                        format="json",
                    )
                results["submit"] = response.status_code
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        submit_thread = Thread(target=submit_worker)
        submit_thread.start()
        delete_response = None
        try:
            self.assertTrue(
                submit_read_sheet.wait(10),
                "submit did not perform its initial unlocked sheet read",
            )
            client = APIClient()
            client.force_authenticate(user=self.respondent)
            delete_response = client.delete(
                reverse("answersheet-detail", args=[self.sheet.pk]),
            )
        finally:
            allow_submit_to_lock.set()
            submit_thread.join(10)

        self.assertFalse(submit_thread.is_alive(), "submit thread did not finish")
        if errors:
            raise errors[0]
        self.assertIsNotNone(delete_response)
        self.assertEqual(
            delete_response.status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertEqual(results["submit"], status.HTTP_404_NOT_FOUND)
        self.assertFalse(AnswerSheet.objects.filter(pk=self.sheet.pk).exists())
        self.assertFalse(
            AnswerText.objects.filter(pk=self.required_answer.pk).exists())
