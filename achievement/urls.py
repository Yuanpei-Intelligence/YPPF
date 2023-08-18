from django.urls import path

from . import views

urlpatterns = [
    path('myself/', views.view_achievements, name='view_achievements'),
]
