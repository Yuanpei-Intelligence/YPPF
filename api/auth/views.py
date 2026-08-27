"""
REST APIs for WeChat mini program login/binding.

逻辑是：
每个微信只能绑定一个主用户，主用户必须是个人用户（小组必须通过个人登录，因为不可能给小组专门搞一个微信号）
个人账户，可能还是一些小组的管理员，那么这个用户可以登录这些小组

## 登录时
用一个wx open id，确定主用户，如果没给username参数，就登录主用户
否则，检查username是否在主用户的可登录账户列表中，如果在，就登录该账户，否则返回错误
wx.login() → code → 后端用 code 向微信换 openid
                         ↓
              查 UserWechatProfile(openid → user)
                         ↓
        ┌────────────────┴────────────────┐
        │ 已绑定                           │ 未绑定
        ↓                                 ↓
   main_user = profile.user           返回 signed_openid
        ↓                         （不透明 one-time 绑定凭据）
   ┌────┴─────────┐
   │ 无 username  │ 有 username 
   ↓              ↓
 用 main_user   检查 username 是否在 main_user 的
 签发 JWT       「可登录账户列表」中
                    ↓
              在 → 用 target_user 签发 JWT（account_id 仍是 main_user）
              不在 → 403

## 绑定时
signed_openid（签名随机 nonce；数据库仅保存摘要）+ username + password
        ↓
验证并锁定 signed_openid（`signed_openid_ttl_minutes` 后过期）
        ↓
authenticate(username, password)
        ↓
密码失败计数按 openid 跨重新签发累计；达到默认 5 次后锁定至 TTL 到期
成功使用后凭据立即失效
        ↓
user 必须是个人账户（不能是组织）
        ↓
检查：该 openid 是否已绑定其他用户 → 是则 400
        ↓
在同一事务中创建 UserWechatProfile(user, openid) 并消费凭据
        ↓
返回 JWT （account id为user）

## 切换账号时
只需要重新调用login API，username设置为要切换的账户username即可

返回的jwt token中，包含以下字段
```
token["sub"] = str(user.pk) # 用户ID （可能是个人账户ID，也可能是组织账户ID）
token["username"] = user.username # 用户名（主账户或者管理的小组）
token["name"] = user.name # 用户姓名
token["account_id"] = account_id # 主账号 username
token["iat"] = int(now.timestamp()) # 签发时间
token["exp"] = int(exp.timestamp()) # 过期时间
token["scope"] = "wx_miniapp" # 作用域
```
额外可以拓展权限字段，待实现
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

from rest_framework_simplejwt.tokens import AccessToken
import requests
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.config import CONFIG
from api.auth.binding import (
    WechatBindingAttemptLimitError,
    WechatBindingAuthenticationError,
    WechatBindingError,
    issue_binding_credential,
    redeem_binding_credential,
)
from api.auth.serializers import WxBindSerializer, WxCodeSerializer
from api.auth.ticket import WEBVIEW_TICKET_TTL, create_webview_ticket
from api.authentication import WxJWTAuthentication
from api.exceptions import (
    APIError,
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)
from generic.models import UserWechatProfile, User
from app.utils import get_person_or_org
from app.models import NaturalPerson, Organization, Position

logger = logging.getLogger(__name__)


def error_response(description: str) -> OpenApiResponse:
    """Document the shared authentication error envelope."""

    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
    )


def _fetch_openid_from_wechat(code: str) -> Tuple[str | None, str | None]:
    """
    Exchange the wx.login code for an openid.

    Returns a tuple of (openid, error_message). Only one of them will be set.
    """
    try:
        appid = CONFIG.appid
        secret = CONFIG.secret
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.error("wx_miniapp appid/secret is not configured", exc_info=exc)
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
    except (requests.RequestException, ValueError) as exc:
        logger.warning("jscode2session request failed", exc_info=exc)
        return None, "无法访问微信登录服务"

    if payload.get("errcode"):
        logger.info(
            "jscode2session rejected login code: errcode=%s",
            payload.get("errcode"),
        )
        return None, "微信登录凭证无效或已过期"

    openid = payload.get("openid")
    if not openid:
        return None, "未能获取到openid"
    return openid, None


def _issue_jwt_for_user(user: User, account_id: str | None = None) -> str:
    """
    Sign a short-lived JWT for the mini program client.
    
    Args:
        user: 当前登录的用户
        account_id: 主账号 username，如果为 None 则自动获取
    """
    if account_id is None:
        account_id = _get_account_id(user)

    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=CONFIG.token_expire_minutes)
    token = AccessToken.for_user(user)
    token["sub"] = str(user.pk)
    token["username"] = user.username
    token["name"] = user.name
    token["account_id"] = account_id
    token["iat"] = int(now.timestamp())
    token["exp"] = int(exp.timestamp())
    token["scope"] = "wx_miniapp"
    return str(token)


def _get_account_id(user: User) -> str | None:
    """
    获取主账号 account_id（username）。
    如果是个人账户，返回 user.username。
    如果是小组账户，返回None
    """
    if user.is_person():
        return user.username
    else:
        return None


def _get_loginable_accounts(account_id: str) -> list[dict]:
    """
    获取 account_id（username）对应的主账号可以登录的所有账户列表。
    返回格式: [{"username": str, "name": str, "type": str, "avatar": str}, ...]
    """
    try:
        main_user = User.objects.get(username=account_id)
    except User.DoesNotExist:
        return []

    accounts = []

    # 添加主账号（个人账户）
    if main_user.is_person():
        classified = get_person_or_org(main_user)
        accounts.append({
            "username": main_user.username,
            "name": main_user.name,
            "type": "person",
            "avatar": classified.get_user_ava(),
        })

        # 获取该个人账户管理的所有组织账户
        try:
            person = NaturalPerson.objects.get_by_user(
                main_user, activate=True)
            positions = Position.objects.activated().filter(
                person=person, is_admin=True
            )
            for position in positions:
                org = position.org
                org_user = org.get_user()
                accounts.append({
                    "username": org_user.username,
                    "name": org.oname,
                    "type": "org",
                    "avatar": org.get_user_ava(),
                })
        except NaturalPerson.DoesNotExist:
            return accounts

    return accounts


def _check_user_in_accounts(username: str, account_id: str) -> bool:
    """
    检查 username 是否在 account_id（username）对应的可登录账户列表中。
    """
    accounts = _get_loginable_accounts(account_id)
    return any(acc["username"] == username for acc in accounts)


class WxCodeLoginView(StandardizedExceptionHandlerMixin, APIView):
    """
    Accepts the temporary code from ``wx.login`` and returns either a JWT
    (for already-bound users) or an opaque one-time ``signed_openid`` binding
    credential. The credential expires after ``signed_openid_ttl_minutes`` and
    is invalid after successful use. Reissuing for the same openid rotates the
    nonce without resetting failures; exhaustion blocks issuance until expiry.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="微信小程序登录",
        description=(
            "使用微信小程序 wx.login() 返回的 code 换取 openid。如果已绑定则返回 JWT；"
            "否则返回不透明的 one-time signed_openid 绑定凭据。该凭据在 "
            "signed_openid_ttl_minutes 后过期；同一 openid 重新签发会轮换 nonce"
            "但不会清零失败次数，达到默认 5 次密码失败后将锁定至 TTL 到期。"
            "可选的 username 参数用于指定登录到哪个账户（必须在可登录账户列表中）。"
        ),
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
                        "account_id": {"type": "string", "description": "主账号 username (仅当 status=bound 时存在)"},
                        "signed_openid": {
                            "type": "string",
                            "description": (
                                "签名随机 nonce 的不透明 one-time 绑定凭据"
                                "（仅当 status=unbound 时存在）"
                            ),
                        },
                        "expires_in": {"type": "integer", "description": "signed_openid/token 过期时间（秒)"},
                    },
                },
            ),
            400: error_response("微信登录凭证或目标账号有误"),
            403: error_response("无权登录目标账号"),
            404: error_response("目标账号不存在"),
            503: error_response("微信登录服务暂时不可用"),
        },
        tags=["微信小程序认证"],
    )
    def post(self, request):
        serializer = WxCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"]
        username = serializer.validated_data.get("username")  # 可选的 username 参数

        openid, error = _fetch_openid_from_wechat(code)
        if error:
            if error == "服务器未配置微信登录能力":
                raise APIError(
                    code='auth.wechat_not_configured',
                    message='服务器暂未配置微信登录能力。',
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if error == "无法访问微信登录服务":
                raise APIError(
                    code='auth.wechat_unavailable',
                    message='微信登录服务暂时不可用，请稍后重试。',
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            raise APIError(
                code='auth.wechat_code_rejected',
                message='微信登录凭证无效或已过期，请重试。',
                errors={'code': [{'code': 'invalid', 'message': '请重新获取微信登录凭证。'}]},
            )

        profile = (
            UserWechatProfile.objects.select_related("user")
            .filter(openid=openid)
            .first()
        )
        # 绑定了微信账号
        if profile is not None:
            # 获取主账号绑定的用户
            main_user = profile.user

            # 如果指定了 username，需要验证权限
            if username:
                # 获取主账号的 account_id
                main_account_id = _get_account_id(main_user)
                if main_account_id is None:
                    raise APIError(
                        code='auth.main_account_unavailable',
                        message='无法确定主账号。',
                    )

                # 检查 username 是否在可登录账户列表中
                if not _check_user_in_accounts(username, main_account_id):
                    raise PermissionDenied('没有登录到该账户的权限。')

                # 获取要登录的用户
                try:
                    target_user = User.objects.get(username=username)
                except User.DoesNotExist as exc:
                    raise NotFound('指定的用户不存在。') from exc

                # 使用目标用户签发 JWT，但 account_id 仍然是主账号的
                token = _issue_jwt_for_user(
                    target_user, account_id=main_account_id)
                return Response(
                    {
                        "status": "bound",
                        "token": token,
                        "token_type": "Bearer",
                        "expires_in": CONFIG.token_expire_minutes * 60,
                        "username": target_user.username,
                        "name": target_user.name,
                        "account_id": main_account_id,
                    }
                )
            else:
                # 默认使用主账号登录
                account_id = _get_account_id(main_user)
                token = _issue_jwt_for_user(main_user, account_id=account_id)
                return Response(
                    {
                        "status": "bound",
                        "token": token,
                        "token_type": "Bearer",
                        "expires_in": CONFIG.token_expire_minutes * 60,
                        "username": main_user.username,
                        "name": main_user.name,
                        "account_id": account_id,
                    }
                )

        # 未绑定微信账号，返回临时 signed_openid 用于后续绑定
        try:
            signed_openid = issue_binding_credential(openid)
        except WechatBindingAttemptLimitError as exc:
            raise APIError(
                code='auth.binding_attempts_exhausted',
                message=str(exc),
                errors={exc.field: [{'code': 'attempts_exhausted', 'message': str(exc)}]},
            ) from exc

        return Response(
            {
                "status": "unbound",
                "signed_openid": signed_openid,
                "expires_in": CONFIG.signed_openid_ttl_minutes * 60,
            }
        )


class WxBindView(StandardizedExceptionHandlerMixin, APIView):
    """
    Redeem an opaque one-time ``signed_openid`` with username/password to bind
    its openid to a Django user and return a JWT. It expires after
    ``signed_openid_ttl_minutes`` and is invalid after success. Failed attempts
    are shared by all credentials for an openid until expiry.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="绑定微信账号",
        description=(
            "使用账号密码兑换不透明的 one-time signed_openid 绑定凭据并绑定微信"
            "账号，绑定成功后返回 JWT。凭据在 signed_openid_ttl_minutes 后过期，"
            "同一 openid 的重新签发不会清零失败次数；达到默认 5 次后锁定至 TTL"
            "到期。"
        ),
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
                        "account_id": {
                            "type": "string",
                            "description": "主账号 username",
                        },
                        "expires_in": {"type": "integer", "description": "token过期时间（秒)"},
                    },
                },
            ),
            400: error_response("绑定凭据或账号不符合绑定条件"),
            401: error_response("账号或密码错误"),
        },
        tags=["微信小程序认证"],
    )
    def post(self, request):
        serializer = WxBindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = redeem_binding_credential(
                signed_openid=serializer.validated_data["signed_openid"],
                username=serializer.validated_data["username"],
                password=serializer.validated_data["password"],
            )
        except WechatBindingAuthenticationError as exc:
            raise APIError(
                code='auth.invalid_credentials',
                message='用户名或密码错误。',
                status_code=status.HTTP_401_UNAUTHORIZED,
                errors={
                    'username': [{'code': 'invalid_credentials', 'message': '请检查用户名。'}],
                    'password': [{'code': 'invalid_credentials', 'message': '请检查密码。'}],
                },
            ) from exc
        except WechatBindingError as exc:
            raise APIError(
                code='auth.binding_rejected',
                message=str(exc),
                errors={exc.field: [{'code': 'invalid', 'message': str(exc)}]},
            ) from exc

        account_id = _get_account_id(user)
        token = _issue_jwt_for_user(user, account_id=account_id)
        return Response(
            {
                "status": "bound",
                "token": token,
                "token_type": "Bearer",
                "username": user.username,
                "account_id": account_id,
                "expires_in": CONFIG.token_expire_minutes * 60,  # in seconds
            }
        )


class WxUnbindView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="解除微信账号绑定",
        description="使用 JWT 解除微信账号绑定",
        responses={
            200: OpenApiResponse(description="成功响应"),
            401: error_response("未认证或令牌无效"),
        },
        tags=["微信小程序认证"],
    )
    def post(self, request):
        UserWechatProfile.objects.filter(user=request.user).delete()

        return Response(status=status.HTTP_200_OK)

class GetMyAccountsView(StandardizedExceptionHandlerMixin, APIView):
    """
    获取当前 account_id 的所有可以登录的用户列表。
    需要 JWT 认证。
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取可登录账户列表",
        description="返回当前主账号 account_id 的所有可以登录的用户列表，包括主账号和管理的组织账户",
        responses={
            200: OpenApiResponse(
                description="成功响应",
                response={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "主账号 username"},
                        "accounts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "username": {"type": "string"},
                                    "name": {"type": "string"},
                                    "type": {"type": "string", "enum": ["person", "org"]},
                                    "avatar": {"type": "string", "description": "头像 URL"},
                                },
                            },
                        },
                    },
                },
            ),
            400: error_response("无法确定主账号"),
            401: error_response("未认证或令牌无效"),
        },
        tags=["微信小程序认证"],
    )
    def get(self, request):
        # 尝试从 JWT token 中获取 account_id
        account_id = None
        if hasattr(request, 'auth') and request.auth:
            # request.auth 是 Token 对象，可以通过 payload 属性访问
            try:
                account_id = request.auth.payload.get('account_id')
            except (AttributeError, KeyError, TypeError):
                pass

        # 如果 token 中没有 account_id，尝试从当前用户获取
        if account_id is None and request.user.is_authenticated:
            account_id = _get_account_id(request.user)

        if account_id is None:
            raise APIError(
                code='auth.main_account_unavailable',
                message='无法确定主账号。',
            )

        accounts = _get_loginable_accounts(account_id)
        return Response({
            "account_id": account_id,
            "accounts": accounts,
        })


class CheckLoginView(StandardizedExceptionHandlerMixin, APIView):
    """
    Check if the user is logged in.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="检查是否登录",
        description="检查当前用户是否登录，如果登录则返回用户信息",
        responses={
            200: OpenApiResponse(description="成功响应", response={
                "type": "object",
                "properties": {
                    "is_login": {"type": "boolean"},
                    "username": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["person", "org"]},
                },
            }),
            401: error_response("未认证或令牌无效"),
        },
        tags=["微信小程序认证"],
    )
    def get(self, request):
        return Response({
            "is_login": True,
            "username": request.user.username,
            "name": request.user.name,
            "type": "person" if request.user.is_person() else "org",
        })


class ExchangeTicketView(StandardizedExceptionHandlerMixin, APIView):
    """
    用 JWT 换取一次性 ticket，用于 webview 跳转登录。
    ticket 在 /redirect/?ticket=xxx 使用一次后立即失效，提高安全性。
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="JWT 换取 ticket",
        description="使用 JWT 换取一次性 ticket，用于 webview 跳转。",
        responses={
            200: OpenApiResponse(
                description="成功",
                response={
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "string", "description": "一次性 ticket"},
                        "expires_in": {"type": "integer", "description": "有效秒数"},
                    },
                },
            ),
            401: error_response("未提供或无效的 JWT"),
        },
        tags=["微信小程序认证"],
    )
    def post(self, request):
        ticket = create_webview_ticket(request.user.pk)
        return Response({
            "ticket": ticket,
            "expires_in": WEBVIEW_TICKET_TTL,
        })
