from django.urls import path
from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('survey/<int:survey_id>/', views.survey, name='survey'),
    # path('survey/<int:survey_id>/submit/', views.submit, name='submit'),
    # path('survey/<int:survey_id>/statistics/', views.statistics, name='statistics'),
    # 之后添加一些问卷修改、删除、创建的url
]