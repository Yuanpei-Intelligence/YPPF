"""
URL routes for mini program authentication.
"""
from django.urls import path

from api.auth.views import WxBindView, WxCodeLoginView, GetMyAccountsView

app_name = "auth"

urlpatterns = [
    path("wx/login/", WxCodeLoginView.as_view(), name="wx-code-login"),
    path("wx/bind/", WxBindView.as_view(), name="wx-bind"),
    path("my-accounts/", GetMyAccountsView.as_view(), name="get-my-accounts"),
]

