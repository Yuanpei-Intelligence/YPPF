from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from questionnaire.models import *
from questionnaire.serializers import *
from questionnaire.permissions import *
from questionnaire.utils import (
    create_answersheet,
    lock_draft_answersheet,
    submit_answersheet,
)


# 用viewsets
class SurveyViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSurveyOwnerOrReadOnly]
    serializer_class = SurveySerializer

    def get_queryset(self):
        if self.request.user.is_staff:
            return Survey.objects.all()
        else:  # 根据发布状态和发布时间来筛选
            return Survey.objects.filter(Q(status=Survey.Status.PUBLISHED) | Q(creator=self.request.user))


class QuestionViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsQuestionOwnerOrReadOnly]
    serializer_class = QuestionSerializer

    def get_queryset(self):
        if self.request.user.is_staff:
            return Question.objects.all()
        else:
            return Question.objects.filter(Q(survey__status=Survey.Status.PUBLISHED) | Q(survey__creator=self.request.user))

    # 只有问卷创始人能创建问题
    def perform_create(self, serializer: QuestionSerializer):
        survey = serializer.validated_data['survey']
        if survey.creator == self.request.user:
            serializer.save()
        else:
            raise PermissionError("只有问卷创始人能添加问题！")

    def perform_update(self, serializer: QuestionSerializer):
        survey = serializer.instance.survey
        if survey != serializer.validated_data['survey']:
            raise PermissionError("禁止修改问题所属问卷！请通过删除后新建完成操作。")
        serializer.save()


class ChoiceViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsChoiceOwnerOrReadOnly]
    serializer_class = ChoiceSerializer

    def get_queryset(self):
        if self.request.user.is_staff:
            return Choice.objects.all()
        else:  # TODO:当数据量大的时候会很慢，考虑优化或者直接删除
            return Choice.objects.filter(Q(question__survey__status=Survey.Status.PUBLISHED) | Q(question__survey__creator=self.request.user))

    # 只有问卷创始人能创建选项，而且只有选择题才能创建选项
    def perform_create(self, serializer: ChoiceSerializer):
        question: Question = serializer.validated_data['question']
        if not question.have_choice():
            raise TypeError("当前问题不能设置选项！")
        elif question.survey.creator != self.request.user:
            raise PermissionError("只有问卷创始人能添加选项！")
        else:
            serializer.save()

    def perform_update(self, serializer: ChoiceSerializer):
        question = serializer.instance.question
        if question != serializer.validated_data['question']:
            raise PermissionError("禁止修改选项所属问题！请通过删除后新建完成操作。")
        serializer.save()


class AnswerTextViewSet(viewsets.ModelViewSet):
    queryset = AnswerText.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsTextOwnerOrAsker]
    serializer_class = AnswerTextSerializer

    def get_queryset(self):
        texts = AnswerText.objects.select_related(
            'answersheet__survey',
            'question__survey',
        )
        if self.action in ('update', 'partial_update', 'destroy'):
            return texts.filter(answersheet__creator=self.request.user)
        if self.action == 'retrieve':
            return texts.filter(
                Q(answersheet__creator=self.request.user)
                | Q(
                    answersheet__survey__creator=self.request.user,
                    answersheet__status=AnswerSheet.Status.SUBMITTED,
                )
            )
        return texts.filter(answersheet__creator=self.request.user)

    def perform_create(self, serializer: AnswerTextSerializer):
        answersheet = serializer.validated_data['answersheet']
        question = serializer.validated_data['question']
        with transaction.atomic():
            locked_sheet = lock_draft_answersheet(
                answersheet.pk,
                self.request.user,
            )
            if question.survey_id != locked_sheet.survey_id:
                raise ValidationError("问题与答卷不属于同一问卷！")
            if AnswerText.objects.filter(
                answersheet=locked_sheet,
                question=question,
            ).exists():
                raise ValidationError("禁止重复提交答案！")
            if locked_sheet.survey.status != Survey.Status.PUBLISHED:
                raise ValidationError("只能创建已发布问卷的答案！")
            serializer.save(answersheet=locked_sheet)

    def perform_update(self, serializer: AnswerTextSerializer):
        answersheet = serializer.instance.answersheet
        question = serializer.instance.question
        validated_sheet = serializer.validated_data.get(
            'answersheet',
            answersheet,
        )
        validated_question = serializer.validated_data.get(
            'question',
            question,
        )
        with transaction.atomic():
            locked_sheet = lock_draft_answersheet(
                answersheet.pk,
                self.request.user,
            )
            try:
                locked_answer = AnswerText.objects.select_for_update().get(
                    pk=serializer.instance.pk,
                    answersheet=locked_sheet,
                )
            except AnswerText.DoesNotExist as exc:
                raise NotFound("答案不存在或已被删除！") from exc
            if locked_sheet.pk != validated_sheet.pk:
                raise ValidationError("禁止修改答案所属答卷！")
            if locked_answer.question_id != validated_question.pk:
                raise ValidationError("禁止修改答案所属问题！")
            serializer.instance = locked_answer
            serializer.save(answersheet=locked_sheet)

    def perform_destroy(self, instance):
        with transaction.atomic():
            locked_sheet = lock_draft_answersheet(
                instance.answersheet_id,
                self.request.user,
            )
            AnswerText.objects.filter(
                pk=instance.pk,
                answersheet=locked_sheet,
            ).delete()

    @action(detail=False, methods=['GET'])
    def answer_owner(self, request):
        text = AnswerText.objects.filter(answersheet__creator=request.user)
        serializer = AnswerTextSerializer(text, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'])
    def survey_owner(self, request):
        text = AnswerText.objects.filter(
            answersheet__survey__creator=request.user,
            answersheet__status=AnswerSheet.Status.SUBMITTED,
        )
        serializer = AnswerTextSerializer(text, many=True)
        return Response(serializer.data)


class AnswerSheetViewSet(viewsets.ModelViewSet):
    queryset = AnswerSheet.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSheetOwnerOrAsker]
    serializer_class = AnswerSheetSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        sheets = AnswerSheet.objects.select_related('survey')
        if self.action == 'retrieve':
            return sheets.filter(
                Q(creator=self.request.user)
                | Q(
                    survey__creator=self.request.user,
                    status=AnswerSheet.Status.SUBMITTED,
                )
            )
        return sheets.filter(creator=self.request.user)

    def perform_create(self, serializer: AnswerSheetSerializer):
        survey = serializer.validated_data['survey']
        serializer.instance = create_answersheet(
            survey.pk,
            self.request.user,
        )

    def perform_destroy(self, instance):
        with transaction.atomic():
            locked_sheet = lock_draft_answersheet(
                instance.pk,
                self.request.user,
            )
            locked_sheet.delete()

    @action(detail=True, methods=['POST'])
    def submit(self, request, *args, **kwargs):
        sheet = self.get_object()
        submitted = submit_answersheet(sheet.pk, request.user)
        return Response(self.get_serializer(submitted).data)

    @action(detail=False, methods=['GET'])
    def answer_owner(self, request):
        sheet = AnswerSheet.objects.filter(creator=request.user)
        serializer = AnswerSheetSerializer(sheet, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'])
    def survey_owner(self, request):
        sheet = AnswerSheet.objects.filter(
            survey__creator=request.user,
            status=AnswerSheet.Status.SUBMITTED,
        )
        serializer = AnswerSheetSerializer(sheet, many=True)
        return Response(serializer.data)
