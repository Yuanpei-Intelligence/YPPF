"""Non-API routes of the timetable app (ICS feed). Mounted at /timetable/ in boot/urls.py."""
from django.urls import path

from timetable import views

app_name = 'timetable'

urlpatterns = [
    path('ics/<uuid:token>.ics', views.ics_feed, name='ics_feed'),
]
