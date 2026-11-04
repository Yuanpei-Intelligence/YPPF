"""
REST APIs of the 北大账号 binding for the mini-program (``/api/v2/pku/``).

Contract: ``timetable/README.md`` §3.4. All endpoints require a mini-program
JWT (``WxJWTAuthentication`` + ``IsAuthenticated``, 401 without one) and a
personal account (403 for organizations and special accounts). Business
failures answer ``{"code": ..., "message": ...}``:

===========================  ======  =============================================
code                         status  when
===========================  ======  =============================================
``INVALID_INPUT``            400     request body failed validation
``IAAA_ERROR``               400     IAAA rejected the login (message = IAAA msg)
``OTP_REQUIRED``             400     IAAA demands a second factor
``CAPTCHA_REQUIRED``         400     IAAA demands a captcha
``NOT_BOUND``                404     consents changed while unbound
``ALREADY_BOUND_ELSEWHERE``  409     the PKU account belongs to another user
``LOCKED``                   429     too many failed logins
``PORTAL_DISABLED``          503     ``pku_portal.enabled`` is false
``PORTAL_UNREACHABLE``       503     pku.edu.cn could not be reached
===========================  ======  =============================================

The password only ever travels in the request body; it is never logged,
persisted, or echoed back.
"""
from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import WxJWTAuthentication
from api.pku_account.serializers import (
    ApiErrorSerializer,
    BindingSerializer,
    PkuConsentsSerializer,
    PkuLoginSerializer,
)
from pku_account.extern.iaaa import (
    CaptchaRequired,
    IaaaError,
    OtpRequired,
    PortalUnreachable,
)
from pku_account.services import (
    AccountLocked,
    AlreadyBoundElsewhere,
    NotBound,
    PortalDisabled,
    binding_payload,
    get_binding,
    login_and_bind,
    unbind,
    update_consents,
)

__all__ = [
    'IsPersonAccount',
    'BindingView',
    'LoginView',
    'UnbindView',
    'ConsentsView',
]

logger = logging.getLogger(__name__)

TAGS = ['北大账号']


class IsPersonAccount(BasePermission):
    """Only valid personal accounts may manage a PKU binding (403 otherwise)."""

    # A dict detail is rendered as the body, matching the ``{code, message}``
    # error shape of this module.
    message = {
        'code': 'PERSON_REQUIRED',
        'message': '请使用个人账号操作北大账号绑定',
    }

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_valid()
            and user.is_person()
        )


def _error(code: str, message: str, http_status: int) -> Response:
    return Response({'code': code, 'message': message}, status=http_status)


def _first_message(errors: Any) -> str:
    # Flatten DRF's nested error structure to one human-readable line.
    if isinstance(errors, dict):
        for field, detail in errors.items():
            text = _first_message(detail)
            if field == 'non_field_errors':
                return text
            return f'{field}: {text}'
        return '请求参数错误'
    if isinstance(errors, (list, tuple)):
        for item in errors:
            return _first_message(item)
        return '请求参数错误'
    return str(errors)


def _field_errors(errors: Any) -> dict[str, list[dict[str, str]]]:
    # Canonical ``{field: [{code, message}]}`` shape shared with api/exceptions.py.
    if not isinstance(errors, dict):
        return {}
    result: dict[str, list[dict[str, str]]] = {}
    for name, value in errors.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        result[str(name)] = [
            {'code': str(getattr(item, 'code', None) or 'invalid'), 'message': str(item)}
            for item in values]
    return result


def _invalid(errors: Any) -> Response:
    return Response(
        {
            'code': 'INVALID_INPUT',
            'message': _first_message(errors),
            'errors': _field_errors(errors),
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


_AUTH_RESPONSES = {
    401: OpenApiResponse(description='未提供或无效的 JWT'),
    403: OpenApiResponse(
        response=ApiErrorSerializer,
        description='非个人账号（PERSON_REQUIRED）',
    ),
}


class _PkuAccountView(APIView):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated, IsPersonAccount]


class BindingView(_PkuAccountView):
    """``GET binding/``: the caller's binding status; safe, no side effects."""

    @extend_schema(
        summary='查询北大账号绑定状态',
        description=(
            '返回当前个人账号的北大账号绑定情况、门户会话状态与授权项。'
            '未绑定时 bound=false，其余字段为空值。'
        ),
        responses={200: BindingSerializer, **_AUTH_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        return Response(binding_payload(get_binding(request.user)))


class LoginView(_PkuAccountView):
    """
    ``POST login/``: log in through IAAA with the submitted credentials and
    bind / refresh the caller's PKU account and portal session.

    Mutates ``PkuAccount`` and ``PkuPortalSession`` through
    ``pku_account.services.login_and_bind``.
    """

    @extend_schema(
        summary='登录北大门户并绑定',
        description=(
            '使用统一身份认证账号密码登录北大门户，成功后绑定到当前个人账号并'
            '保存加密的门户会话；密码仅用于本次登录，不会被保存。'
            '可同时提交课表 / 成绩授权。'
        ),
        request=PkuLoginSerializer,
        responses={
            200: BindingSerializer,
            400: OpenApiResponse(
                response=ApiErrorSerializer,
                description=(
                    'INVALID_INPUT / IAAA_ERROR / OTP_REQUIRED / '
                    'CAPTCHA_REQUIRED'
                ),
            ),
            409: OpenApiResponse(
                response=ApiErrorSerializer,
                description='ALREADY_BOUND_ELSEWHERE：该北大账号已绑定其他用户',
            ),
            429: OpenApiResponse(
                response=ApiErrorSerializer,
                description='LOCKED：登录失败次数过多，暂时锁定',
            ),
            503: OpenApiResponse(
                response=ApiErrorSerializer,
                description='PORTAL_DISABLED / PORTAL_UNREACHABLE',
            ),
            **_AUTH_RESPONSES,
        },
        tags=TAGS,
    )
    def post(self, request):
        serializer = PkuLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer.errors)
        data = serializer.validated_data
        user = request.user
        try:
            account = login_and_bind(
                user,
                data['username'],
                data['password'],
                consent_timetable=data.get('consent_timetable'),
                consent_grades=data.get('consent_grades'),
            )
        except PortalDisabled as exc:
            return _error('PORTAL_DISABLED', str(exc), 503)
        except AccountLocked as exc:
            logger.info('PKU login refused for user #%s: locked', user.pk)
            return _error('LOCKED', str(exc), status.HTTP_429_TOO_MANY_REQUESTS)
        except AlreadyBoundElsewhere as exc:
            logger.info(
                'PKU login refused for user #%s: bound elsewhere', user.pk,
            )
            return _error('ALREADY_BOUND_ELSEWHERE', str(exc), 409)
        except OtpRequired as exc:
            return _error('OTP_REQUIRED', exc.msg, 400)
        except CaptchaRequired as exc:
            return _error('CAPTCHA_REQUIRED', exc.msg, 400)
        except IaaaError as exc:
            logger.info(
                'PKU login failed for user #%s: IAAA %s', user.pk, exc.code,
            )
            return _error('IAAA_ERROR', exc.msg, 400)
        except PortalUnreachable as exc:
            logger.warning(
                'PKU login failed for user #%s: portal unreachable', user.pk,
            )
            return _error('PORTAL_UNREACHABLE', str(exc), 503)
        return Response(binding_payload(account))


class UnbindView(_PkuAccountView):
    """``POST unbind/``: delete the caller's binding and stored session."""

    @extend_schema(
        summary='解除北大账号绑定',
        description='删除当前个人账号的北大账号绑定及其门户会话；未绑定时同样返回 204。',
        request=None,
        responses={204: OpenApiResponse(description='已解绑'), **_AUTH_RESPONSES},
        tags=TAGS,
    )
    def post(self, request):
        unbind(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConsentsView(_PkuAccountView):
    """``PATCH consents/``: change the timetable / grades consent flags."""

    @extend_schema(
        summary='更新数据授权',
        description='部分更新课表 / 成绩授权；省略的项保持不变。未绑定时返回 404 NOT_BOUND。',
        request=PkuConsentsSerializer,
        responses={
            200: BindingSerializer,
            400: OpenApiResponse(
                response=ApiErrorSerializer, description='INVALID_INPUT',
            ),
            404: OpenApiResponse(
                response=ApiErrorSerializer, description='NOT_BOUND',
            ),
            **_AUTH_RESPONSES,
        },
        tags=TAGS,
    )
    def patch(self, request):
        serializer = PkuConsentsSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer.errors)
        data = serializer.validated_data
        try:
            account = update_consents(
                request.user,
                timetable=data.get('timetable'),
                grades=data.get('grades'),
            )
        except NotBound as exc:
            return _error('NOT_BOUND', str(exc), status.HTTP_404_NOT_FOUND)
        return Response(binding_payload(account))
