from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from openpyxl import Workbook
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

# TODO: Leaky dependency
from utils.marker import fix_me
from app.models import NaturalPerson
from app.view.base import ProfileTemplateView
from dormitory.config import dormitory_config as CONFIG
from dormitory.models import Dormitory, DormitoryAssignment, Agreement
from dormitory.serializers import (
    DormitoryAssignmentSerializer, DormitorySerializer,
    AgreementSerializerFixme, AgreementSerializer)
from questionnaire.models import AnswerSheet, AnswerText, Question, Survey
from questionnaire.utils import create_answersheet, submit_answersheet
from questionnaire.validators import validate_answer_body

class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DormitoryAssignmentSerializer

    def get_queryset(self):
        user = self.request.user
        assignments = (DormitoryAssignment.objects
                       .filter(active=True)
                       .select_related('dormitory'))
        if (not user.is_authenticated or not user.active
                or not user.is_person()):
            return assignments.none()
        return assignments.filter(user=user)


class DormitoryAgreementViewSetFixme(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AgreementSerializerFixme

    def requires_agreement(self):
        user = self.request.user
        return (user.is_authenticated and user.active
                and user.is_student())

    def get_queryset(self):
        # Only active students need to sign the agreement
        if self.requires_agreement():
            return Agreement.objects.filter(user=self.request.user)
        return Agreement.objects.none()

    def list(self, request, *args, **kwargs):
        if not self.requires_agreement():
            # Keep the legacy frontend's non-empty list contract without
            # creating a synthetic Agreement during GET.
            return Response([{'id': 0}])
        return super().list(request, *args, **kwargs)


class DormitoryAgreementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AgreementSerializer

    def get_queryset(self):
        user = self.request.user
        if (not user.is_authenticated or not user.active
                or not user.is_person()):
            return Agreement.objects.none()
        return Agreement.objects.filter(user=user)


@method_decorator(csrf_protect, name='dispatch')
class DormitoryRoutineQAView(ProfileTemplateView):

    template_name = 'dormitory/routine_QA.html'
    page_name = '生活习惯调研'
    need_prepare = False

    def get_survey(self):
        return Survey.objects.get(title=CONFIG.routine_qa_survey_title)

    def _build_survey_iter(self, survey):
        """Build survey_iter with (question, choices, submitted_value) tuples."""
        return [
            (question, question.choices.order_by('order'),
             self._normalize_answer(question))
            for question in survey.questions.order_by('order')
        ]

    def _normalize_answer(self, question):
        """Extract and normalize the submitted answer for a question."""
        key = str(question.order)
        if question.type == 'MULTIPLE':
            values = [v for v in self.request.POST.getlist(key) if v]
            return ','.join(values)
        value = (self.request.POST.get(key) or '').strip()
        return value

    def get(self):
        survey = self.get_survey()
        if AnswerSheet.objects.filter(creator=self.request.user,
                                      survey=survey).exists():
            return self.render(submitted=True)
        survey_iter = [
            (question, question.choices.order_by('order'), '')
            for question in survey.questions.order_by('order')
        ]
        return self.render(survey_iter=survey_iter)

    def post(self):
        survey = self.get_survey()

        # Collect submitted answers for repopulation on validation failure
        submitted = {
            str(q.order): self._normalize_answer(q)
            for q in survey.questions.order_by('order')
        }
        survey_iter = [
            (question, question.choices.order_by('order'),
             submitted.get(str(question.order), ''))
            for question in survey.questions.order_by('order')
        ]
        render_kwargs = dict(survey_iter=survey_iter)

        for question in survey.questions.order_by('order'):
            answer = submitted[str(question.order)]
            if not answer:
                if question.required:
                    return self.render(
                        html_display=dict(
                            warn_code=1,
                            warn_message=f'必填题{question.order}未作答',
                        ),
                        **render_kwargs,
                    )
                continue
            try:
                validate_answer_body(question, answer)
            except ValidationError as exc:
                return self.render(
                    html_display=dict(
                        warn_code=1,
                        warn_message=f'第{question.order}题：{exc.messages[0]}',
                    ),
                    **render_kwargs,
                )

        # Validate that the "学号" answer matches the current user's username
        sid_question = survey.questions.filter(topic='学号', type=Question.Type.TEXT).first()
        if sid_question:
            sid_answer = submitted.get(str(sid_question.order), '')
            if sid_answer != self.request.user.username:
                return self.render(
                    html_display=dict(
                        warn_code=1,
                        warn_message='学号与当前登录账号不匹配，请重新填写！'
                    ),
                    **render_kwargs,
                )

        # Validate that the "姓名" answer matches the user's registered name
        name_question = survey.questions.filter(topic='姓名', type=Question.Type.TEXT).first()
        if name_question:
            name_answer = submitted.get(str(name_question.order), '')
            if name_answer != self.request.user.name:
                return self.render(
                    html_display=dict(
                        warn_code=1,
                        warn_message='填写的姓名与系统中信息不一致。'
                        '如姓名录入有误，请联系管理员修改。'
                    ),
                    **render_kwargs,
                )

        if survey.status != Survey.Status.PUBLISHED:
            return self.render(
                html_display=dict(
                    warn_code=1,
                    warn_message='只能提交已发布的问卷！',
                ),
                **render_kwargs,
            )

        try:
            with transaction.atomic():
                sheet = create_answersheet(survey.pk, self.request.user)
                for question in survey.questions.order_by('order'):
                    answer = submitted[str(question.order)]
                    if not answer:
                        continue
                    AnswerText.objects.create(question=question,
                                              answersheet=sheet,
                                              body=answer)
                submit_answersheet(sheet.pk, self.request.user)
        except DRFValidationError as exc:
            message = exc.detail[0] if exc.detail else '问卷提交失败，请稍后重试。'
            return self.render(
                html_display=dict(
                    warn_code=1,
                    warn_message=str(message),
                ),
                **render_kwargs,
            )
        return self.render(submitted=True)


class DormitoryAssignResultView(ProfileTemplateView):

    template_name = 'dormitory/assign_result.html'
    page_name = '宿舍分配结果'
    http_method_names = ['get']
    need_prepare = False

    def get(self):
        self.show_dorm_assign()
        return self.render()

    def show_dorm_assign(self):
        user = self.request.user
        try:
            active_assignments = DormitoryAssignment.objects.filter(active=True)
            assignment = active_assignments.get(user=user)
            dorm_assignment = active_assignments.filter(
                dormitory=assignment.dormitory)
            roommates = [NaturalPerson.objects.get_by_user(assign.user)
                         for assign in dorm_assignment.exclude(user=user)]
            self.extra_context.update(
                dorm_assigned=True,
                name=user.get_full_name(),
                dorm_id=assignment.dormitory.id,
                bed_id=assignment.bed_id,
                roommates=roommates,
            )
        except DormitoryAssignment.DoesNotExist:
            self.extra_context.update(dorm_assigned=False)


class AgreementView(ProfileTemplateView):
    template_name = 'dormitory/agreement.html'
    page_name = '住宿协议'
    need_prepare = False

    def get(self):
        return self.render()

    @fix_me
    def post(self):
        Agreement.objects.get_or_create(user=self.request.user)
        from django.shortcuts import redirect
        return redirect("/welcome")
