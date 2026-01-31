"""
User profile APIs.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from rest_framework import serializers

from api.authentication import WxJWTAuthentication


class DailyLoginResponseSerializer(serializers.Serializer):
    """Response serializer for daily login (sign-in) endpoint."""

    message = serializers.CharField(
        help_text="Sign-in result or status message")
from app.models import NaturalPerson
from app.utils import get_user_wallpaper, get_person_or_org
from generic.models import User

from app.YQPoint_utils import add_signin_point
from django.db import transaction
from datetime import datetime


def _serialize_me(user: User) -> dict:
    """
    Serialize current authenticated user's profile.

    This endpoint is meant for "my profile" so we can return more fields than
    public profile pages, but we still keep the payload stable and minimal.
    """
    try:
        classified = get_person_or_org(user)
    except AssertionError:
        raise PermissionDenied("不存在对应的自然人或组织，该账号不可登录小程序")


    base = {
        "id": user.pk,
        "username": user.username,
        "name": user.name,
        "utype": user.utype,
        "active": user.active,
        "is_staff": user.is_staff,
        "is_person": user.is_person(),
        "is_org": user.is_org(),
        "avatar_url": classified.get_user_ava(),
        "wallpaper_url": get_user_wallpaper(classified),
        "absolute_url": classified.get_absolute_url(),
    }

    # Type-specific fields
    if user.is_person():
        # NaturalPerson fields
        base.update(
            {
                "profile": {
                    "nickname": getattr(classified, "nickname", None),
                    "gender": getattr(classified, "gender", None),
                    "birthday": getattr(classified, "birthday", None),
                    "email": getattr(classified, "email", None),
                    "telephone": getattr(classified, "telephone", None),
                    "biography": getattr(classified, "biography", None),
                    "identity": getattr(classified, "identity", None),
                    "status": getattr(classified, "status", None),
                    "stu_class": getattr(classified, "stu_class", None),
                    "stu_major": getattr(classified, "stu_major", None),
                    "stu_grade": getattr(classified, "stu_grade", None),
                    "stu_dorm": getattr(classified, "stu_dorm", None),
                    "inform_share": getattr(classified, "inform_share", None),
                }
            }
        )
    elif user.is_org():
        base.update(
            {
                "profile": {
                    "oname": getattr(classified, "oname", None),
                    "introduction": getattr(classified, "introduction", None),
                    "status": getattr(classified, "status", None),
                    "inform_share": getattr(classified, "inform_share", None),
                }
            }
        )
    else:
        base.update({"profile": {}})

    return base


class MeView(APIView):
    """
    Return the current authenticated user's own profile info.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取本人信息",
        description="返回当前登录用户（本人）的个人信息/小组信息",
        responses={
            200: OpenApiResponse(
                description="本人信息",
                response={
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "username": {"type": "string"},
                        "name": {"type": "string"},
                        "utype": {"type": "string"},
                        "active": {"type": "boolean"},
                        "is_staff": {"type": "boolean"},
                        "is_person": {"type": "boolean"},
                        "is_org": {"type": "boolean"},
                        "avatar_url": {"type": "string"},
                        "wallpaper_url": {"type": "string"},
                        "absolute_url": {"type": "string"},
                        "profile": {"type": "object"},
                    },
                },
            ),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=["用户"],
    )
    def get(self, request):
        return Response(_serialize_me(request.user))


class DailyLoginView(APIView):
    """
    Daily login, add YQPoint for user if not logged in today
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]
    serializer_class = DailyLoginResponseSerializer

    @extend_schema(
        summary="每日登录",
        description="每日登录，如果用户今天未登录，则添加 YQPoint",
        responses={
            200: DailyLoginResponseSerializer,
            401: OpenApiResponse(description="未登录"),
        },
        tags=["用户"],
    )
    def post(self, request):
        nowtime = datetime.now()
        # 今天第一次访问 welcome 界面，积分增加
        if request.user.is_person():
            with transaction.atomic():
                np = NaturalPerson.objects.get_by_user(
                    request.user, update=True)
                if np.last_time_login is None or np.last_time_login.date() != nowtime.date():
                    np.last_time_login = nowtime
                    np.save()
                    n, notice = add_signin_point(request.user)
                    return Response({"message": notice}, status=200)
        return Response({"message": "今日已登录"}, status=200)
