from django.urls import path
from questionnaire import views


urlpatterns = [
    path('survey/',views.SurveyViewSet.as_view({'get':'list','post':'create'})),
    path('survey/<int:pk>/',views.SurveyViewSet.as_view({'get':'retrieve','put':'update','delete':'destroy'})),
    path('question/',views.QuestionViewSet.as_view({'get':'list','post':'create'})),
    path('question/<int:pk>/',views.QuestionViewSet.as_view({'get':'retrieve','put':'update','delete':'destroy'})),
    path('choice/',views.ChoiceViewSet.as_view({'get':'list','post':'create'})),
    path('choice/<int:pk>/',views.ChoiceViewSet.as_view({'get':'retrieve','put':'update','delete':'destroy'})),
    path('answersheet/',views.AnswerSheetViewSet.as_view({'get':'list','post':'create'})),
    path('answersheet/<int:pk>/',views.AnswerSheetViewSet.as_view({'get':'retrieve','put':'update','delete':'destroy'})),
    path('answertext/',views.AnswerTextViewSet.as_view({'get':'list','post':'create'})),
    path('answertext/<int:pk>/',views.AnswerTextViewSet.as_view({'get':'retrieve','put':'update','delete':'destroy'})),
]

