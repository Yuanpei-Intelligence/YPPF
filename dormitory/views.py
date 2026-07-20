from django.db import transaction
from rest_framework import viewsets

# TODO: Leaky dependency
from utils.marker import fix_me
from generic.models import User
from app.models import NaturalPerson
from app.view.base import ProfileTemplateView
from dormitory.config import dormitory_config as CONFIG
from dormitory.models import Dormitory, DormitoryAssignment, Agreement
from dormitory.serializers import (
    DormitoryAssignmentSerializer, DormitorySerializer,
    AgreementSerializerFixme, AgreementSerializer)
from questionnaire.models import AnswerSheet, AnswerText, Question, Survey
from django.http import HttpResponse
from openpyxl import Workbook

class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DormitoryAssignment.objects.filter(active = True)
    serializer_class = DormitoryAssignmentSerializer


class DormitoryAgreementViewSetFixme(viewsets.ReadOnlyModelViewSet):
    serializer_class = AgreementSerializerFixme

    def get_queryset(self):
        # Only active students need to sign the agreement
        require_agreement = User.objects.filter(active=True,
                                                utype=User.Type.STUDENT).contains(self.request.user)
        if require_agreement:
            return Agreement.objects.filter(user=self.request.user)
        # A hack to return something, so that the frontend won't redirect
        official_user = User.objects.get(username='zz00000')
        Agreement.objects.get_or_create(user=official_user)
        return Agreement.objects.filter(user=official_user)


class DormitoryAgreementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Agreement.objects.all()
    serializer_class = AgreementSerializer


class DormitoryRoutineQAView(ProfileTemplateView):

    template_name = 'dormitory/routine_QA.html'
    page_name = '生活习惯调研'
    need_prepare = False

    def get_survey(self):
        return Survey.objects.get(title=CONFIG.routine_qa_survey_title)

    def get(self):
        survey = self.get_survey()
        if AnswerSheet.objects.filter(creator=self.request.user,
                                      survey=survey).exists():
            return self.render(submitted=True)
        return self.render(survey_iter=[
            (question, question.choices.order_by('order'))
            for question in survey.questions.order_by('order')
        ])

    def post(self):
        survey = self.get_survey()
        assert not AnswerSheet.objects.filter(creator=self.request.user,
                                              survey=survey).exists()

        def _normalize_answer(question):
            key = str(question.order)
            if question.type == 'MULTIPLE':
                values = [value for value in self.request.POST.getlist(key) if value]
                return ','.join(values)
            value = (self.request.POST.get(key) or '').strip()
            if question.type in ['SINGLE', 'RANKING']:
                return value
            if question.type == 'TEXT':
                return value
            return value

        # Validate that the "学号" answer matches the current user's username
        sid_question = survey.questions.filter(topic='学号', type=Question.Type.TEXT).first()
        if sid_question:
            sid_answer = _normalize_answer(sid_question)
            if sid_answer != self.request.user.username:
                return self.render(
                    html_display=dict(
                        warn_code=1,
                        warn_message='学号与当前登录账号不匹配，请重新填写！'
                    ),
                    survey_iter=[
                        (question, question.choices.order_by('order'))
                        for question in survey.questions.order_by('order')
                    ],
                )

        # Validate that the "姓名" answer matches the user's registered name
        name_question = survey.questions.filter(topic='姓名', type=Question.Type.TEXT).first()
        if name_question:
            name_answer = _normalize_answer(name_question)
            if name_answer != self.request.user.name:
                return self.render(
                    html_display=dict(
                        warn_code=1,
                        warn_message='填写的姓名与系统中信息不一致。'
                        '如姓名录入有误，请联系管理员修改。'
                    ),
                    survey_iter=[
                        (question, question.choices.order_by('order'))
                        for question in survey.questions.order_by('order')
                    ],
                )

        with transaction.atomic():
            sheet = AnswerSheet.objects.create(creator=self.request.user,
                                               survey=survey)
            for question in survey.questions.order_by('order'):
                answer = _normalize_answer(question)
                if not answer:
                    if question.required:
                        raise ValueError(f'必填题{question.order}未作答')
                    continue
                AnswerText.objects.create(question=question,
                                          answersheet=sheet,
                                          body=answer)
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
            assignment = DormitoryAssignmentViewSet.queryset.get(user=user)
            dorm_assignment = DormitoryAssignmentViewSet.queryset.filter(
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
