"""
URL routes for notification API.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from api.notification.views import NotificationViewSet

app_name = "notification"

router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = router.urls
