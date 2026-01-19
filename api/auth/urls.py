"""
URL routes for mini program authentication.
"""
from django.urls import path

from api.auth.views import WxBindView, WxCodeLoginView

app_name = "auth"

urlpatterns = [
    path("wx/login/", WxCodeLoginView.as_view(), name="wx-code-login"),
    path("wx/bind/", WxBindView.as_view(), name="wx-bind"),
]

