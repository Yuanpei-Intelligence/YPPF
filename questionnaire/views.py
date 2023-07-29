from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse

from rest_framework import viewsets

from questionnaire.models import Survey, AnswerSheet, Question, Choice, AnswerText
from questionnaire.serializers import SurveySerializer, AnswerSheetSerializer, QuestionSerializer, ChoiceSerializer, AnswerTextSerializer

# Create your views here.
def index(request):
    return HttpResponse("Hello, world. You're at the questionnaire index.")

# 用viewsets
class SurveyViewSet(viewsets.ModelViewSet):
    queryset = Survey.objects.all()
    serializer_class = SurveySerializer

class AnswerSheetViewSet(viewsets.ModelViewSet):
    queryset = AnswerSheet.objects.all()
    serializer_class = AnswerSheetSerializer

class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.all()
    serializer_class = QuestionSerializer

class ChoiceViewSet(viewsets.ModelViewSet):
    queryset = Choice.objects.all()
    serializer_class = ChoiceSerializer

class AnswerTextViewSet(viewsets.ModelViewSet):
    queryset = AnswerText.objects.all()
    serializer_class = AnswerTextSerializer

# class UserViewSet(viewsets.ModelViewSet):
    # queryset = User.objects.all().order_by("-date_joined")
    # serializer_class = UserSerializer

