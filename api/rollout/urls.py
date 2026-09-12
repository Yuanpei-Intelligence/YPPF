"""
URL routes for rollout API.
"""
from django.urls import path

from api.rollout.views import PreviewMembershipView, RolloutStateView

app_name = "rollout"

urlpatterns = [
    path("features/", RolloutStateView.as_view(), name="features"),
    path("preview/", PreviewMembershipView.as_view(), name="preview"),
]
