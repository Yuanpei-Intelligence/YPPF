"""
URL routes for appointment API.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from api.appoint.views import (
    AppointViewSet,
    StatusView,
    AgreementView,
    ArrangeTimeView,
    ArrangeTalkRoomView,
    CheckoutAppointView,
    MyAppointmentsView,
    MyViolationsView,
    SearchUsersView,
)

app_name = "appoint"

router = DefaultRouter()
# 取消和续约
router.register(r'appointments', AppointViewSet, basename='appointment')

urlpatterns = [
    path('my-appointments/', MyAppointmentsView.as_view(), name='my-appointments'),
    path('my-violations/', MyViolationsView.as_view(), name='my-violations'),
    path('status/', StatusView.as_view(), name='status'),
    path('agreement/', AgreementView.as_view(), name='agreement'),
    path('arrange-by-room/', ArrangeTimeView.as_view(), name='arrange-by-room'),
    path('arrange-talk-room-by-time/', ArrangeTalkRoomView.as_view(),
         name='arrange-talk-room-by-time'),
    path('checkout/', CheckoutAppointView.as_view(), name='checkout'),
    path('search-users/', SearchUsersView.as_view(), name='search-users'),
] + router.urls
