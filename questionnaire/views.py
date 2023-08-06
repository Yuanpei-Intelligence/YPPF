from django.db.models import Q

from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response

from questionnaire.models import *
from questionnaire.serializers import *
from questionnaire.permissions import *

from django.utils import timezone

# 用viewsets
class SurveyViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSurveyOwnerOrReadOnly]
    serializer_class = SurveySerializer

    def get_queryset(self):
        if self.request.user.is_staff:
            return Survey.objects.all()
        else: # 根据发布状态和发布时间来筛选 
            # TODO: 自动更新问卷状态
            return Survey.objects.filter(Q(status=Survey.Status.PUBLISHED) | Q(creator=self.request.user))


class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.all() # TODO: 问题和选项的queryset应该也需要重写？
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsQuestionOwnerOrReadOnly]
    serializer_class = QuestionSerializer

    # only the owner of the survey can create its questions
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
    queryset = Choice.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsChoiceOwnerOrReadOnly]
    serializer_class = ChoiceSerializer

    # only the owner of the question can create its choices && the question must can have choices
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

    def list(self, request, *args, **kwargs):
        raise PermissionError("禁止直接查看所有答案！")

    def perform_create(self, serializer):
        answersheet = serializer.validated_data['answersheet']
        question = serializer.validated_data['question']
        if answersheet.creator != self.request.user:
            raise PermissionError("只有答卷创始人才能添加答案！")
        elif AnswerText.objects.filter(answersheet=answersheet, question=question).exists():
            raise PermissionError("禁止重复提交答案！")
        elif answersheet.survey.status != 1:
            raise PermissionError("只能创建已发布问卷的答案！")
        else:
            serializer.save()
    
    def perform_update(self, serializer):
        raise PermissionError("禁止修改答案！")
    
    @action(detail=False, methods=['GET'])
    def answer_owner(self, request):
        text = AnswerText.objects.filter(answersheet__creator=request.user)
        serializer = AnswerTextSerializer(text, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['GET'])
    def survey_owner(self, request):
        text = AnswerText.objects.filter(question__survey__creator=request.user)
        serializer = AnswerTextSerializer(text, many=True)
        return Response(serializer.data)


class AnswerSheetViewSet(viewsets.ModelViewSet):
    queryset = AnswerSheet.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSheetOwnerOrAsker]
    serializer_class = AnswerSheetSerializer

    def list(self, request, *args, **kwargs):
        raise PermissionError("禁止直接查看所有答卷！")

    def perform_create(self, serializer):
        creator = serializer.validated_data['creator']
        survey = serializer.validated_data['survey']
        if survey.status != 1: # 问卷必须处于发布状态才能创建答卷
            raise PermissionError("只能创建已发布问卷的答案！")
        elif AnswerSheet.objects.filter(creator=creator, survey=survey).exists():
            raise PermissionError("禁止重复创建答卷！")
        else:
            serializer.save()
    
    def perform_update(self, serializer):
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
        
