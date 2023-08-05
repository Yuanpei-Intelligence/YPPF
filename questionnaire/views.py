from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from utils.global_messages import message_url, wrong

from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action

from questionnaire.models import *
from questionnaire.serializers import *
from questionnaire.permissions import *

from django.utils import timezone

# 用viewsets
class SurveyViewSet(viewsets.ModelViewSet):
    queryset = Survey.objects.all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSurveyOwnerOrReadOnly]
    serializer_class = SurveySerializer
    # TODO: 
    # 在发布时间内才能对一般用户可见
    def get_queryset(self):
        if self.request.user.is_staff:
            return Survey.objects.all()
        else: # 根据发布状态和发布时间来筛选 
            return Survey.objects.filter(status=Survey.Status.PUBLISHED, start_time__lte=timezone.now(), end_time__gte=timezone.now())

    # 必须和user相同，而且信息不冲突才能创建，问卷状态必须和发布时间匹配
    def perform_create(self, serializer):
        if serializer.validated_data['creator'] == self.request.user:
            start_time = serializer.validated_data['start_time']
            end_time = serializer.validated_data['end_time']
            if start_time >= end_time:
                raise TypeError # 问卷时间设置冲突 
            serializer.save()
        else:
            raise PermissionError # 创建人与用户不匹配

    # 如果要更改，必须是发布者
    def perform_update(self, serializer):
        if serializer.validated_data['creator'] == self.request.user:
            start_time = serializer.validated_data['start_time']
            end_time = serializer.validated_data['end_time']
            if start_time >= end_time:
                raise TypeError # 问卷时间设置冲突 
            serializer.save()
        else:
            raise PermissionError # 更改人与创建人不匹配

    # 如果要删除，必须是发布者 其实这个没太有必要 因为之前权限已经杜绝了这个情况
    def perform_destroy(self, instance):
        if instance.creator == self.request.user:
            instance.delete()
        else: 
            raise PermissionError # 删除人与创建人不匹配

    # 不能轻易更改发布者
    @action(detail=True, methods=['put'])
    def change_creator(self, request, pk=None):
        survey = self.get_object()
        if survey.creator == self.request.user:
            survey.creator = request.data['creator']
            survey.save()
            return PermissionError # 创建人被更改
        else:
            raise PermissionError


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
            raise PermissionError # 创建人与用户不匹配
        
    # only the owner of the survey can update its questions
    def perform_update(self, serializer):
        survey = serializer.validated_data['survey']
        if survey.creator == self.request.user:
            serializer.save()
        else:
            raise PermissionError # 更改人与创建人不匹配
        
    # only the owner of the survey can delete its questions
    def perform_destroy(self, instance):
        survey = instance.survey
        if survey.creator == self.request.user:
            instance.delete()
        else:
            raise PermissionError # 删除人与创建人不匹配


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

    # only the owner of the question can update its choices
    def perform_update(self, serializer):
        question = serializer.validated_data['question']
        if question.survey.creator == self.request.user:
            serializer.save()
        else:
            raise PermissionError # 更改人与创建人不匹配
        
    # only the owner of the question can delete its choices
    def perform_destroy(self, instance):
        question = instance.question
        if question.survey.creator == self.request.user:
            instance.delete()
        else:
            raise PermissionError # 删除人与创建人不匹配


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
    
    # 只能访问自己的答案
    def get_queryset(self):
        return AnswerText.objects.filter(answersheet__creator=self.request.user)
    
    # 谁能删除 这里有待考虑
    def perform_destroy(self, instance):
        raise PermissionError


class AnswerSheetViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSheetOwnerOrAsker]
    serializer_class = AnswerSheetSerializer

    def perform_create(self, serializer):
        creator = serializer.validated_data['creator']
        survey = serializer.validated_data['survey']
        if survey.status != 1: # 问卷必须处于发布状态才能创建答卷
            raise PermissionError # 不在发布期内，不能创建
        elif creator != self.request.user:
            raise PermissionError
        elif AnswerSheet.objects.filter(creator=creator, survey=survey).exists():
            raise PermissionError
        else:
            serializer.save()
    
    def perform_update(self, serializer):
        raise PermissionError

    # TODO: 禁止list的接口，分别设置作为问卷所有人和答卷人的查看接口 这里还是有点问题 感觉需要从前端解决
    def get_queryset(self):
        if self.request.user.is_staff:
            return AnswerSheet.objects.all()
        else:
            return AnswerSheet.objects.filter(creator=self.request.user)
        
    # 谁能删除 这里有待考虑
    def perform_destroy(self, instance):
        raise PermissionError