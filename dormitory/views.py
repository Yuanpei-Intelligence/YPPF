from django.db import transaction
from rest_framework import viewsets

# TODO: Leaky dependency
from generic.models import User
from app.models import NaturalPerson
from app.view.base import ProfileTemplateView, ProfileJsonView
from dormitory.models import Dormitory, DormitoryAssignment, Agreement
from dormitory.serializers import (DormitoryAssignmentSerializer,
                                   DormitorySerializer,
                                   AgreementSerializer)
from questionnaire.models import AnswerSheet, AnswerText, Survey


class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DormitoryAssignment.objects.all()
    serializer_class = DormitoryAssignmentSerializer


class DormitoryAgreementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AgreementSerializer
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


class DormitoryRoutineQAView(ProfileTemplateView):

    template_name = 'dormitory/routine_QA.html'
    page_name = '生活习惯调研'
    need_prepare = False

    def get_survey(self):
        return Survey.objects.get(title='宿舍生活习惯调研')

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
        with transaction.atomic():
            sheet = AnswerSheet.objects.create(creator=self.request.user,
                                               survey=survey)
            for question in survey.questions.order_by('order'):
                answer = self.request.POST.get(str(question.order))
                if answer is None:
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
                dorm_assign=True,
                name=user.get_full_name(),
                dorm_id=assignment.dormitory.id,
                bed_id=assignment.bed_id,
                roommates=roommates,
            )
        except DormitoryAssignment.DoesNotExist:
            self.extra_context.update(dorm_assign=False)

class AgreementView(ProfileTemplateView):
    template_name = 'dormitory/agreement.html'
    page_name = '住宿协议'
    need_prepare = False

    def get(self):
        return self.render()

    def post(self):
        Agreement.objects.get_or_create(user=self.request.user)
        return self.render()

