from rest_framework import viewsets
from django.db import transaction

# TODO: Leaky dependency
from app.view.base import ProfileTemplateView
from questionnaire.models import Survey, AnswerSheet, AnswerText
from dormitory.models import Dormitory, DormitoryAssignment
from dormitory.serializers import DormitorySerializer, DormitoryAssignmentSerializer


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
