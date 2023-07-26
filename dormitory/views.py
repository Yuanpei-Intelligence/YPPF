from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse

from .models import Survey, AnswerSheet, Question, Choice, AnswerText, SurveyStatistics


# 首页
def index(request):
    # 获取所有问卷
    surveys = Survey.objects.all()
    # 渲染首页
    return render(request, 'dormitory/index.html', {'surveys': surveys})


# 问卷
def survey(request, questionnaire_id):
    # 获取问卷
    survey = get_object_or_404(Survey, pk=questionnaire_id)
    # 获取问卷所有问题
    questions = survey.survey_question.all()
    # 获取问卷所有问题的选项
    choices = []
    for question in questions:
        choices.append(question.question_choice.all())
    # 渲染问卷
    return render(request, 'dormitory/survey.html', {'survey': survey, 'questions': questions, 'choices': choices})