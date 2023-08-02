from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse

from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action

from questionnaire.models import *
from questionnaire.serializers import *
from questionnaire.permissions import *

# Create your views here.
def index(request):
    return HttpResponse("Hello, world. You're at the questionnaire index.")

# 用viewsets
class SurveyViewSet(viewsets.ModelViewSet):
    queryset = Survey.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSurveyOwnerOrReadOnly]
    serializer_class = SurveySerializer
    # TODO: 添加时间判断


class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsQuestionOwnerOrReadOnly]
    serializer_class = QuestionSerializer

    # only the owner of the survey can create its questions
    def perform_create(self, serializer):
        survey = serializer.validated_data['survey']
        if survey.creator == self.request.user:
            serializer.save()
        else:
            raise PermissionError


class ChoiceViewSet(viewsets.ModelViewSet):
    queryset = Choice.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsChoiceOwnerOrReadOnly]
    serializer_class = ChoiceSerializer

    # only the owner of the question can create its choices && the question must can have choices
    def perform_create(self, serializer):
        question = serializer.validated_data['question']
        if not question.have_choice():
            raise TypeError # 这个错误随便给的，后面再改
        elif question.survey.creator != self.request.user:
            raise PermissionError
        else:
            serializer.save()


class AnswerTextViewSet(viewsets.ModelViewSet):
    queryset = AnswerText.objects.all() # 但是！我们应该“禁止”访问answertext的list方法，应当都去访问answersheet！
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsTextOwnerOrAsker]
    serializer_class = AnswerTextSerializer

    def perform_create(self, serializer):
        answersheet = serializer.validated_data['answersheet']
        question = serializer.validated_data['question']
        if answersheet.creator != self.request.user: # 禁止非本人创建答案
            raise PermissionError
        elif AnswerText.objects.filter(answersheet=answersheet, question=question).exists(): # 禁止重复创建答案
            raise PermissionError # 也是随便写的错误
        else:
            serializer.save()
    
    def perform_update(self, serializer):
        raise PermissionError # 生成后禁止修改答案


class AnswerSheetViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSheetOwnerOrAsker]
    serializer_class = AnswerSheetSerializer

    def perform_create(self, serializer):
        creator = serializer.validated_data['creator']
        survey = serializer.validated_data['survey']
        if creator != self.request.user:
            raise PermissionError
        elif AnswerSheet.objects.filter(creator=creator, survey=survey).exists():
            raise PermissionError
        else:
            serializer.save()
    
    def perform_update(self, serializer):
        raise PermissionError

    # TODO: 禁止list的接口，分别设置作为问卷所有人和答卷人的查看接口
    def get_queryset(self):
        return AnswerSheet.objects.all()