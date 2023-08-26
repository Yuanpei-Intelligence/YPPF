from django.db import transaction
from rest_framework import viewsets

# TODO: Leaky dependency
from app.models import NaturalPerson
from app.view.base import ProfileTemplateView
from dormitory.models import Dormitory, DormitoryAssignment
from dormitory.serializers import (DormitoryAssignmentSerializer,
                                   DormitorySerializer)
from questionnaire.models import AnswerSheet, AnswerText, Survey


class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DormitoryAssignment.objects.all()
    serializer_class = DormitoryAssignmentSerializer


class DormitoryRoutineQAView(ProfileTemplateView):

    template_name = 'dormitory/dormitory_routine_QA.html'
    page_name = '生活习惯调研'

    def prepare_get(self):
        return self.get

    def prepare_post(self):
        return self.post

    def get(self):

        survey = Survey.objects.get(title='宿舍调查问卷')
        if AnswerSheet.objects.filter(creator=self.request.user,
                                      survey=survey).exists():
            self.extra_context.update({
                'submitted': True
            })
            return self.render()
        questions = survey.question_set.order_by('order').all()
        choices = [
            question.choices.order_by('order').all() for question in questions
        ]
        self.extra_context.update({
            'survey_iter': zip(questions, choices),
        })
        return self.render()

    def post(self):
        survey = Survey.objects.get(title='宿舍调查问卷')
        assert not AnswerSheet.objects.filter(creator=self.request.user,
                                              survey=survey).exists()
        with transaction.atomic():
            sheet = AnswerSheet.objects.create(creator=self.request.user,
                                               survey=survey)
            for question in survey.question_set.order_by('order').all():
                answer = self.request.POST.get(str(question.order))
                if answer is None:
                    continue
                AnswerText.objects.create(question=question,
                                          answersheet=sheet,
                                          body=answer)
        self.extra_context.update({
            'submitted': True
        })
        return self.render()


class DormitoryAssignResultView(ProfileTemplateView):

    template_name = 'dormitory/dormitory_assign_result.html'
    page_name = '宿舍分配结果'

    def prepare_get(self):
        return self.get

    def get(self):
        self.show_dorm_assign()
        return self.render()

    def show_dorm_assign(self):
        user = self.request.user
        np_student = NaturalPerson.objects.get(person_id=user)
        try:
            user_assignment = DormitoryAssignmentViewSet.queryset.get(
                user=user)
            dorm_assignment = DormitoryAssignmentViewSet.queryset.filter(
                dormitory=user_assignment.dormitory)
            name, dorm_id, bed_id = np_student.name, user_assignment.dormitory.id, dorm_assignment.get(
                user=user).bed_id
            roommates = [NaturalPerson.objects.get(
                person_id=item.user) for item in dorm_assignment]
            roommates.remove(np_student)
            self.extra_context.update({
                'dorm_assigned': True,
                'name': name,
                'dorm_id': dorm_id,
                'bed_id': bed_id,
                'roommates': [(i, item) for i, item in enumerate(roommates)],
                'rommmates_total': str(len(roommates))
            })
        except DormitoryAssignment.DoesNotExist:
            self.extra_context.update({
                'dorm_assigned': False,
            })
