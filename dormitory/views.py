from rest_framework import viewsets
from django.db import transaction

# TODO: Leaky dependency
from app.view.base import ProfileTemplateView
from questionnaire.models import Survey, AnswerSheet, AnswerText
from dormitory.models import Dormitory, DormitoryAssignment
from dormitory.serializers import DormitorySerializer, DormitoryAssignmentSerializer
from generic.models import User
from app.models import NaturalPerson
from app.views import stuinfo

class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DormitoryAssignment.objects.all()
    serializer_class = DormitoryAssignmentSerializer


class TemporaryDormitoryView(ProfileTemplateView):

    template_name = 'dormitory/temporary_dormitory.html'
    page_name = '生活习惯调研'

    def prepare_get(self):
        return self.get

    def prepare_post(self):
        return self.post

    def get(self):
        user = self.request.user
        np_student = NaturalPerson.objects.get(person_id=user)
        survey = Survey.objects.get(title='宿舍调查问卷')
        if AnswerSheet.objects.filter(creator=self.request.user,
                                      survey=survey).exists():
            self.extra_context.update({
                'submitted': True
            })
            try:
                user_assignment = DormitoryAssignmentViewSet.queryset.get(user=user)
                dorm_assignment = DormitoryAssignmentViewSet.queryset.filter(dormitory=user_assignment.dormitory)
                name, dorm_id, bed_id = np_student.name, user_assignment.dormitory.id, dorm_assignment.get(user=user).bed_id
                roommates = [ NaturalPerson.objects.get(person_id=item.user) for item in dorm_assignment]
                roommates.remove(np_student)
                self.extra_context.update({
                    'dorm_assigned': True,
                    'name': name,
                    'dorm_id': dorm_id,
                    'bed_id': bed_id,
                    'roommates_first' : roommates[:1],
                    'roommates_rest' : roommates[1:],
                })
            except DormitoryAssignment.DoesNotExist:
                self.extra_context.update({
                    'dorm_assigned': False,
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