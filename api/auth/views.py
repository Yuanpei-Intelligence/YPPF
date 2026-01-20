"""
REST APIs for WeChat mini program login/binding.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

from rest_framework_simplejwt.tokens import AccessToken
import requests
from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.config import CONFIG
from api.auth.serializers import WxBindSerializer, WxCodeSerializer
from generic.models import UserWechatProfile, User

logger = logging.getLogger(__name__)


def _fetch_openid_from_wechat(code: str) -> Tuple[str | None, str | None]:
    """
    Exchange the wx.login code for an openid.

    Returns a tuple of (openid, error_message). Only one of them will be set.
    """
    try:
        appid = CONFIG.appid
        secret = CONFIG.secret
    except Exception as exc:  # noqa: BLE001 - config loading issues
        logger.error("wx_miniapp appid/secret is not configured: %s", exc)
        return None, "服务器未配置微信登录能力"

    params = {
        "appid": appid,
        "secret": secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        resp = requests.get(CONFIG.jscode2session_url, params=params, timeout=5)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - we want to surface network issues
        logger.warning("jscode2session request failed: %s", exc)
        return None, "无法访问微信登录服务"

    if payload.get("errcode"):
        logger.info("jscode2session returned error: %s", payload)
        return None, payload.get("errmsg") or "微信登录失败"

    openid = payload.get("openid")
    if not openid:
        return None, "未能获取到openid"
    return openid, None


def _issue_jwt_for_user(user: User) -> str:
    """
    Sign a short-lived JWT for the mini program client.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=CONFIG.token_expire_minutes)
    token = AccessToken.for_user(user)
    token["sub"] = str(user.pk)
    token["username"] = user.username
    token["name"] = user.name
    token["iat"] = int(now.timestamp())
    token["exp"] = int(exp.timestamp())
    token["scope"] = "wx_miniapp"
    return str(token)


def _sign_openid(openid: str) -> str:
    """
    Issue a signed token that encodes the openid and expires quickly.
    """
    signer = signing.TimestampSigner(salt="wx_miniapp_openid")
    return signer.sign(openid)


def _unsign_openid(signed_openid: str) -> str:
    """
    Validate and extract the openid from a signed token.
    """
    signer = signing.TimestampSigner(salt="wx_miniapp_openid")
    return signer.unsign(
        signed_openid, max_age=CONFIG.signed_openid_ttl_minutes * 60
    )


class WxCodeLoginView(APIView):
    """
    Accepts the temporary code from ``wx.login`` and returns either a JWT
    (for already-bound users) or a short-lived signed_openid for binding.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="微信小程序登录",
        description="使用微信小程序 wx.login() 返回的 code 换取 openid，如果已绑定则返回 JWT，否则返回 signed_openid 用于后续绑定",
        request=WxCodeSerializer,
        responses={
            200: OpenApiResponse(
                description="成功响应",
                response={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["bound", "unbound"]},
                        "token": {"type": "string", "description": "JWT token (仅当 status=bound 时存在)"},
                        "token_type": {"type": "string", "description": "Bearer (仅当 status=bound 时存在)"},
                        "username": {"type": "string", "description": "用户名 (仅当 status=bound 时存在)"},
                        "name": {"type": "string", "description": "用户名称 (仅当 status=bound 时存在)"},
                        "signed_openid": {"type": "string", "description": "签名的 openid (仅当 status=unbound 时存在)"},
                        "expires_in": {"type": "integer", "description": "signed_openid/token 过期时间（秒)"},
                    },
                },
            ),
            400: OpenApiResponse(description="请求错误，如 code 无效或微信服务异常"),
        },
        tags=["微信小程序认证"],
    )
    def post(self, request):
        serializer = WxCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"]

        openid, error = _fetch_openid_from_wechat(code)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        profile = (
            UserWechatProfile.objects.select_related("user")
            .filter(openid=openid)
            .first()
        )
        if profile is not None:
            token = _issue_jwt_for_user(profile.user)
            return Response(
                {
                    "status": "bound",
                    "token": token,
                    "token_type": "Bearer",
                    "expires_in": CONFIG.token_expire_minutes * 60, # in seconds
                    "username": profile.user.username,
                    "name": profile.user.name,
                }
            )

        signed_openid = _sign_openid(openid)
        # print("signed:", signed_openid)

        return Response(
            {
                "status": "unbound",
                "signed_openid": signed_openid,
                "expires_in": CONFIG.signed_openid_ttl_minutes * 60,
            }
        )


class WxBindView(APIView):
    """
    Bind an openid to a Django user using username/password and return a JWT.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="绑定微信账号",
        description="使用账号密码和 signed_openid 绑定微信账号，绑定成功后返回 JWT",
        request=WxBindSerializer,
        responses={
            200: OpenApiResponse(
                description="绑定成功",
                response={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["bound"]},
                        "token": {"type": "string", "description": "JWT token"},
                        "token_type": {"type": "string", "description": "Bearer"},
                        "username": {"type": "string", "description": "用户名"},
                        "expires_in": {"type": "integer", "description": "token过期时间（秒)"},
                    },
                },
            ),
            400: OpenApiResponse(description="请求错误，如 signed_openid 无效或已过期"),
            401: OpenApiResponse(description="认证失败，账号或密码错误"),
        },
        tags=["微信小程序认证"],
    )
    def post(self, request):
        serializer = WxBindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # print("Received", serializer.validated_data["signed_openid"])

        try:
            openid = _unsign_openid(serializer.validated_data["signed_openid"])
        except signing.SignatureExpired as exc:
            raise ValidationError({"signed_openid": "签名已过期，请重新登录微信授权"}) from exc
        except signing.BadSignature as exc:
            raise ValidationError({"signed_openid": "无效的签名，请重新登录微信授权"}) from exc

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        user = authenticate(username=username, password=password)
        if user is None:
            raise AuthenticationFailed("账号或密码错误")

        with transaction.atomic():
            if (
                UserWechatProfile.objects.select_for_update()
                .filter(openid=openid)
                .exclude(user=user)
                .exists()
            ):
                raise ValidationError({"signed_openid": "该微信已绑定其他账号"})

            profile, created = UserWechatProfile.objects.select_for_update().get_or_create(
                user=user, defaults={"openid": openid}
            )
            if not created and profile.openid != openid:
                profile.openid = openid
                profile.save(update_fields=["openid"])

        token = _issue_jwt_for_user(user)
        return Response(
            {
                "status": "bound",
                "token": token,
                "token_type": "Bearer",
                "username": user.username,
                "expires_in": CONFIG.token_expire_minutes * 60, # in seconds
            }
        )

