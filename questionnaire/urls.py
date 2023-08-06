from django.urls import path, include
from rest_framework.routers import DefaultRouter
from questionnaire.views import *

router = DefaultRouter()
router.register(r'survey', SurveyViewSet, basename="survey")
router.register(r'answersheet', AnswerSheetViewSet, basename="answersheet")
router.register(r'answertext', AnswerTextViewSet, basename="answertext")
router.register(r'question', QuestionViewSet, basename="question")
router.register(r'choice', ChoiceViewSet, basename="choice")

urlpatterns = [
    path('', include(router.urls)), 
]
