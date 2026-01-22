"""
URL routes for appointment API.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from api.appoint.views import (
    AppointViewSet,
    AccountView,
    CreditView,
    StatusView,
    AgreementView,
    ArrangeTimeView,
    ArrangeTalkRoomView,
    CheckoutAppointView,
)

app_name = "appoint"

router = DefaultRouter()
router.register(r'appointments', AppointViewSet, basename='appointment')

urlpatterns = [
    path('account/', AccountView.as_view(), name='account'),
    path('credit/', CreditView.as_view(), name='credit'),
    path('status/', StatusView.as_view(), name='status'),
    path('agreement/', AgreementView.as_view(), name='agreement'),
    path('arrange-time/', ArrangeTimeView.as_view(), name='arrange-time'),
    path('arrange-talk-room/', ArrangeTalkRoomView.as_view(),
         name='arrange-talk-room'),
    path('checkout/', CheckoutAppointView.as_view(), name='checkout'),
] + router.urls
