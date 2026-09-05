from django.urls import path

from birthboard import (
    views,
)
from birthboard.api_yqpoint import check_yqpoint

urlpatterns = [
    path("", views.birthboard, name="birthboard"),
    path("contract/", views.birthboard_contract, name="birthboard_contract"),
    path("api/sign_contract/", views.birthboard_sign_contract, name="birthboard_sign_contract"),
    path(
        'media/<int:record_id>/<str:kind>/',
        views.birthboard_image,
        name='birthboard_image',
    ),
    path("confirm/", views.birthboard_confirm, name="birthboard_confirm"),
    path("approve/", views.birthboard_approve, name="birthboard_approve"),
    path("approve/denied/", views.birthboard_approve_denied, name="birthboard_approve_denied"),
] + [
    path("check_yqpoint/", check_yqpoint, name="check_yqpoint"),
    path("api/check_yqpoint/", check_yqpoint, name="check_yqpoint_api"),
    path("api/confirm_count/", views.confirm_tab_count_api, name="confirm_tab_count_api"),
    path("api/like_count/", views.birthboard_like_count, name="birthboard_like_count"),
    path("api/like_add/", views.birthboard_like_add, name="birthboard_like_add"),
    path("api/reminder_seen/", views.birthboard_reminder_seen, name="birthboard_reminder_seen"),
]
