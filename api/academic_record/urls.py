"""
URL routes for the grades (academic_record) mini-program API.
Contract: timetable/README.md §6.2. Mounted at ``/api/v2/grades/``.
"""
from django.urls import path

from api.academic_record.views import GradesView, SyncView

app_name = "academic_record"

urlpatterns = [
    path('', GradesView.as_view(), name='grades'),
    path('sync/', SyncView.as_view(), name='sync'),
]
