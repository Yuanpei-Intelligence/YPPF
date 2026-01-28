"""
URL routes for group (organization) subscription API.
"""
from django.urls import path

from api.group.views import SubscriptionListView, SubscriptionUpdateView

app_name = "group"

urlpatterns = [
    path('subscriptions/', SubscriptionListView.as_view(), name='subscription-list'),
    path('subscriptions/update/', SubscriptionUpdateView.as_view(), name='subscription-update'),
]
