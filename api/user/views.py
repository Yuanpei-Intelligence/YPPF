"""
User profile APIs.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import WxJWTAuthentication
from api.exceptions import (
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)
from api.user.serializers import (
    DailyLoginResponseSerializer,
    MeResponseSerializer,
)
from app.YQPoint_utils import add_signin_point
from app.models import NaturalPerson
from app.utils import get_person_or_org, get_user_wallpaper
from generic.models import User


def _serialize_me(user: User) -> dict:
    """
    Serialize current authenticated user's profile.

    This endpoint is meant for "my profile" so we can return more fields than
    public profile pages, but we still keep the payload stable and minimal.
    """
    if not user.is_valid():
        raise PermissionDenied("该账号不可登录小程序。")
    classified = get_person_or_org(user)

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


def error_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
    )


class MeView(StandardizedExceptionHandlerMixin, APIView):
    """
    Return the current authenticated user's own profile info.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取本人信息",
        description="返回当前登录用户（本人）的个人信息/小组信息",
        responses={
            200: MeResponseSerializer,
            401: error_response("未认证或令牌无效"),
            403: error_response("当前账号不支持小程序登录"),
            405: error_response("请求方法不受支持"),
            500: error_response("服务器暂时无法处理请求"),
        },
        tags=["用户"],
    )
    def get(self, request):
        return Response(_serialize_me(request.user))


class DailyLoginView(StandardizedExceptionHandlerMixin, APIView):
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
            401: error_response("未认证或令牌无效"),
            405: error_response("请求方法不受支持"),
            500: error_response("服务器暂时无法处理请求"),
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
                if (
                    np.last_time_login is None
                    or np.last_time_login.date() != nowtime.date()
                ):
                    np.last_time_login = nowtime
                    np.save(update_fields=["last_time_login"])
                    _points, notice = add_signin_point(request.user)
                    return Response(
                        {"message": notice},
                        status=status.HTTP_200_OK,
                    )
        return Response(
            {"message": "今日已登录"},
            status=status.HTTP_200_OK,
        )
