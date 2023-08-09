from django.urls import path

from . import views

urlpatterns = [
    path('achievement/', views.view_achievements, name='view_achievements'),
    # Add other URLs as needed
]
