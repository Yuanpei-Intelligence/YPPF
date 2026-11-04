"""URL routes for the 北大账号 (pku_account) mini-program API. Contract: timetable/README.md §3.4."""
from django.urls import path

from api.pku_account.views import (
    BindingView,
    ConsentsView,
    LoginView,
    UnbindView,
)

app_name = "pku_account"

urlpatterns = [
    path("binding/", BindingView.as_view(), name="binding"),
    path("login/", LoginView.as_view(), name="login"),
    path("unbind/", UnbindView.as_view(), name="unbind"),
    path("consents/", ConsentsView.as_view(), name="consents"),
]
