from django.urls import path, include
from rest_framework.routers import DefaultRouter

from questionnaire.views import (
    QuestionViewSet, ChoiceViewSet, SurveyViewSet,
    AnswerSheetViewSet, AnswerTextViewSet
)

router = DefaultRouter()
router.register('survey', SurveyViewSet, basename="survey")
router.register('answersheet', AnswerSheetViewSet, basename="answersheet")
router.register('answertext', AnswerTextViewSet, basename="answertext")
router.register('question', QuestionViewSet, basename="question")
router.register('choice', ChoiceViewSet, basename="choice")

urlpatterns = [
    path('', include(router.urls)), 
]
