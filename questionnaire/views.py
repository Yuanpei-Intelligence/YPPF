from django.db.models import Q
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response

from questionnaire.models import *
from questionnaire.serializers import *
from questionnaire.permissions import *


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
    def perform_create(self, serializer):
        survey = serializer.validated_data['survey']
        if survey.creator == self.request.user:
            serializer.save()
        else:
            raise PermissionError("只有问卷创始人能添加问题！")

    def perform_update(self, serializer):
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
    def perform_create(self, serializer):
        question = serializer.validated_data['question']
        if not question.have_choice():
            raise TypeError("当前问题不能设置选项！")
        elif question.survey.creator != self.request.user:
            raise PermissionError("只有问卷创始人能添加选项！")
        else:
            serializer.save()

    def perform_update(self, serializer):
        question = serializer.instance.question
        if question != serializer.validated_data['question']:
            raise PermissionError("禁止修改选项所属问题！请通过删除后新建完成操作。")
        serializer.save()


class AnswerTextViewSet(viewsets.ModelViewSet):
    queryset = AnswerText.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsTextOwnerOrAsker]
    serializer_class = AnswerTextSerializer

    # debug时可以注释掉
    def list(self, request, *args, **kwargs):
        raise PermissionError("禁止直接查看所有答案！")

    def perform_create(self, serializer):
        answersheet = serializer.validated_data['answersheet']
        question = serializer.validated_data['question']
        if answersheet.creator != self.request.user:
            raise PermissionError("只有答卷创始人才能添加答案！")
        elif AnswerText.objects.filter(answersheet=answersheet, question=question).exists():
            raise PermissionError("禁止重复提交答案！")
        elif answersheet.survey.status != Survey.Status.PUBLISHED:
            raise PermissionError("只能创建已发布问卷的答案！")
        else:
            serializer.save()

    def perform_update(self, serializer):
        answersheet = serializer.instance.answersheet
        question = serializer.instance.question
        if answersheet.status == AnswerSheet.Status.DRAFT:
            if answersheet.creator != self.request.user:
                raise PermissionError("只有答卷创始人才能修改答案！")
            if answersheet != serializer.validated_data['answersheet']:
                raise PermissionError("禁止修改答案所属答卷！")
            if question != serializer.validated_data['question']:
                raise PermissionError("禁止修改答案所属问题！")
            serializer.save()
        else:
            raise PermissionError("禁止修改答案！")

    @action(detail=False, methods=['GET'])
    def answer_owner(self, request):
        text = AnswerText.objects.filter(answersheet__creator=request.user)
        serializer = AnswerTextSerializer(text, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'])
    def survey_owner(self, request):
        text = AnswerText.objects.filter(
            question__survey__creator=request.user)
        serializer = AnswerTextSerializer(text, many=True)
        return Response(serializer.data)


class AnswerSheetViewSet(viewsets.ModelViewSet):
    queryset = AnswerSheet.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSheetOwnerOrAsker]
    serializer_class = AnswerSheetSerializer

    # debug时可以注释掉
    def list(self, request, *args, **kwargs):
        raise PermissionError("禁止直接查看所有答卷！")

    def perform_create(self, serializer):
        creator = serializer.validated_data['creator']
        survey = serializer.validated_data['survey']
        if survey.status != Survey.Status.PUBLISHED:  # 问卷必须处于发布状态才能创建答卷
            raise PermissionError("只能创建已发布问卷的答案！")
        elif AnswerSheet.objects.filter(creator=creator, survey=survey).exists():
            raise PermissionError("禁止重复创建答卷！")
        else:
            serializer.save()

    def perform_update(self, serializer):
        sheet_status = serializer.instance.status
        if sheet_status == AnswerSheet.Status.DRAFT:
            survey = serializer.instance.survey
            if survey != serializer.validated_data['survey']:
                raise PermissionError("禁止修改答卷所属问卷！")
            serializer.save()  # 此部分中只能修改提交状态
        else:
            raise PermissionError("禁止修改答卷！")

    @action(detail=False, methods=['GET'])
    def answer_owner(self, request):
        sheet = AnswerSheet.objects.filter(creator=request.user)
        serializer = AnswerSheetSerializer(sheet, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'])
    def survey_owner(self, request):
        sheet = AnswerSheet.objects.filter(survey__creator=request.user)
        serializer = AnswerSheetSerializer(sheet, many=True)
        return Response(serializer.data)
