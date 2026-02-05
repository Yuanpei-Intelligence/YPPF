"""
URL routes for mini program authentication.
"""
from django.urls import path

from api.auth.views import (
    WxBindView,
    WxCodeLoginView,
    GetMyAccountsView,
    CheckLoginView,
    ExchangeTicketView,
    WxUnbindView,
)

app_name = "auth"

urlpatterns = [
    path("wx/login/", WxCodeLoginView.as_view(), name="wx-code-login"),
    path("wx/bind/", WxBindView.as_view(), name="wx-bind"),
    path("wx/unbind/", WxUnbindView.as_view(), name="wx-unbind"),
    path("my-accounts/", GetMyAccountsView.as_view(), name="get-my-accounts"),
    path("check-login/", CheckLoginView.as_view(), name="check-login"),
    path("ticket/", ExchangeTicketView.as_view(), name="exchange-ticket"),
]

