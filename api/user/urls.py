"""
URL routes for user-related APIs.
"""

from django.urls import path

from api.user.views import MeView

app_name = "user"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
]


