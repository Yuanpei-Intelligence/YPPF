"""URL routes for the timetable mini-program API. Contract: timetable/README.md §4.6, §6, §8.6."""
from django.urls import path

from api.timetable.views import (
    AgendaView,
    CatalogAddView,
    CatalogView,
    EntryViewSet,
    IcsRotateView,
    IcsView,
    ImportPortalView,
    ImportTextView,
    SettingsView,
    ShareAssetsView,
    SubscribeGrantView,
    SubscribeTemplatesView,
    TermsView,
    WeekView,
)

app_name = "timetable"

entry_list = EntryViewSet.as_view({'get': 'list', 'post': 'create'})
entry_detail = EntryViewSet.as_view(
    {'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})
entry_overrides = EntryViewSet.as_view({'delete': 'reset_overrides'})
entry_override_detail = EntryViewSet.as_view({'delete': 'delete_override'})

urlpatterns = [
    path('terms/', TermsView.as_view(), name='terms'),
    path('week/', WeekView.as_view(), name='week'),
    path('agenda/', AgendaView.as_view(), name='agenda'),
    path('entries/', entry_list, name='entry-list'),
    path('entries/<int:pk>/', entry_detail, name='entry-detail'),
    path('entries/<int:pk>/overrides/', entry_overrides, name='entry-overrides'),
    path('entries/<int:pk>/overrides/<int:oid>/', entry_override_detail,
         name='entry-override-detail'),
    path('import/portal/', ImportPortalView.as_view(), name='import-portal'),
    path('import/text/', ImportTextView.as_view(), name='import-text'),
    path('settings/', SettingsView.as_view(), name='settings'),
    path('ics/', IcsView.as_view(), name='ics'),
    path('ics/rotate/', IcsRotateView.as_view(), name='ics-rotate'),
    path('subscribe-templates/', SubscribeTemplatesView.as_view(),
         name='subscribe-templates'),
    path('subscribe-grant/', SubscribeGrantView.as_view(), name='subscribe-grant'),
    path('catalog/', CatalogView.as_view(), name='catalog'),
    path('catalog/<int:pk>/add/', CatalogAddView.as_view(), name='catalog-add'),
    path('share/assets/', ShareAssetsView.as_view(), name='share-assets'),
]
