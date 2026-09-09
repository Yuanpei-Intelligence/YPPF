"""URL routes for the timetable mini-program API. Contract: timetable/README.md §4.6, §6."""
from django.urls import path

from api.timetable.views import (
    AgendaView,
    CatalogView,
    EntryViewSet,
    IcsRotateView,
    IcsView,
    ImportPortalView,
    ImportTextView,
    SettingsView,
    SubscribeGrantView,
    SubscribeTemplatesView,
    TermsView,
    WeekView,
)

app_name = "timetable"

entry_list = EntryViewSet.as_view({'get': 'list', 'post': 'create'})
entry_detail = EntryViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'})

urlpatterns = [
    path('terms/', TermsView.as_view(), name='terms'),
    path('week/', WeekView.as_view(), name='week'),
    path('agenda/', AgendaView.as_view(), name='agenda'),
    path('entries/', entry_list, name='entry-list'),
    path('entries/<int:pk>/', entry_detail, name='entry-detail'),
    path('import/portal/', ImportPortalView.as_view(), name='import-portal'),
    path('import/text/', ImportTextView.as_view(), name='import-text'),
    path('settings/', SettingsView.as_view(), name='settings'),
    path('ics/', IcsView.as_view(), name='ics'),
    path('ics/rotate/', IcsRotateView.as_view(), name='ics-rotate'),
    path('subscribe-templates/', SubscribeTemplatesView.as_view(),
         name='subscribe-templates'),
    path('subscribe-grant/', SubscribeGrantView.as_view(), name='subscribe-grant'),
    path('catalog/', CatalogView.as_view(), name='catalog'),
]
