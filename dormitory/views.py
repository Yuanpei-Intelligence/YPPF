from django.db import transaction
from rest_framework import viewsets

# TODO: Leaky dependency
from utils.marker import fix_me
from generic.models import User
from app.models import NaturalPerson
from app.view.base import ProfileTemplateView
from dormitory.models import Dormitory, DormitoryAssignment, Agreement
from dormitory.serializers import (
    DormitoryAssignmentSerializer, DormitorySerializer,
    AgreementSerializerFixme, AgreementSerializer)
from questionnaire.models import AnswerSheet, AnswerText, Survey
from semester.api import current_semester
from django.http import HttpResponse
from openpyxl import Workbook

class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DormitoryAssignment.objects.all()
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
        return Survey.objects.get(title=f'宿舍生活习惯调研-{current_semester().year}')

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
                    assert not question.required, f"必填题{question.order}未作答"
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



def download_xlsx(request) -> HttpResponse:
    wb = Workbook()
    ws = wb.active
    ws.title = "Result"

    survey = Survey.objects.get(title='宿舍生活习惯调研-2024')
    questions = survey.questions.order_by('order').all()

    # Add header row
    headers = [question.topic for question in questions]
    for col_num, column_title in enumerate(headers, 1):
        col_letter = ws.cell(row=1, column=col_num)
        col_letter.value = column_title

    # Iterate through the AnswerSheet objects
    for row_num, answer_sheet in enumerate(AnswerSheet.objects.filter(survey=survey), 2):
        answers = {answer.question.id: answer for answer in answer_sheet.answertext_set.all()}
        for col_num, question in enumerate(questions, 1):
            col_letter = ws.cell(row=row_num, column=col_num)
            answer = answers.get(question.id)
            if answer:
                if question.type == 'TEXT':
                    col_letter.value = answer.body
                elif question.type == 'SINGLE':
                    t = list(question.choices.filter(order=int(answer.body)))
                    if len(t) != 1:
                        raise ValueError(t)
                    col_letter.value = question.choices.get(order=int(answer.body)).text
                elif question.type == 'MULTIPLE':
                    choices_orders = answer.body.split(',')
                    choices_texts = [question.choices.get(order=int(order)).text for order in choices_orders]
                    col_letter.value = ', '.join(choices_texts)
            else:
                # If no answer, set as empty or a default value
                col_letter.value = None  # or you can use "" or "N/A"

    # Save and return the workbook
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=questions.xlsx'
    wb.save(response)

    return response
