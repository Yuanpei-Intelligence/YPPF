"""
URL routes for user-related APIs.
"""

from django.urls import path

from api.user.views import MeView, DailyLoginView

app_name = "user"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("daily-login/", DailyLoginView.as_view(), name="daily-login"),
]


