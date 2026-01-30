"""
URL routes for feedback API.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from api.feedback.views import FeedbackViewSet

app_name = "feedback"

router = DefaultRouter()
router.register(r"", FeedbackViewSet, basename="feedback")

urlpatterns = [
    path("", include(router.urls)),
]
