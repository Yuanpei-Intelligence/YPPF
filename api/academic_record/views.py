"""
REST APIs of the grades (成绩) for the WeChat mini-program.
Contract: ``timetable/README.md`` §6.2. Mounted at ``/api/v2/grades/``.

Every endpoint requires a mini-program JWT (``WxJWTAuthentication`` +
``IsAuthenticated``) and a personal account; organization accounts get 403.
Errors are ``{code, message}`` bodies:

=======================  ======  ==============================================
code                     status  when
=======================  ======  ==============================================
``not_authenticated``    401     no bearer token
``invalid_token``        401     malformed / expired token
``permission_denied``    403     not a personal account
``CONSENT_REQUIRED``     403     ``GET`` without ``consent_grades``
``NOT_BOUND``            404     no PKU account binding
``PKU_LOGIN_REQUIRED``   409     no usable portal session; log in again
``PARSE_FAILED``         400     the portal answered without a score list
``PORTAL_DISABLED``      503     ``pku_portal.enabled`` is false
``PORTAL_UNREACHABLE``   503     pku.edu.cn could not be reached
=======================  ======  ==============================================

No credentials pass through here; score payloads are never logged.
"""
from __future__ import annotations

import logging
from datetime import datetime

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import NaturalPerson
from api.authentication import WxJWTAuthentication
from api.academic_record.serializers import GradesErrorSerializer, GradesOutSerializer
from pku_account.extern.iaaa import PortalUnreachable
from pku_account.extern.portal import PortalSessionExpired
from pku_account.services import (
    NotBound,
    PortalDisabled,
    SessionUnavailable,
    get_binding,
)
from academic_record import services

__all__ = [
    'ApiError',
    'GradesAPIView',
    'GradesView',
    'SyncView',
]

logger = logging.getLogger(__name__)

TAGS = ['成绩']


class ApiError(APIException):
    """A ``{code, message}`` error with an explicit HTTP status."""

    def __init__(self, code: str, message: str, status_code: int):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(detail=message, code=code)


def _first_error(detail) -> str:
    # First human-readable message of a DRF error detail.
    if isinstance(detail, dict):
        for value in detail.values():
            return _first_error(value)
        return ''
    if isinstance(detail, (list, tuple)):
        return _first_error(detail[0]) if detail else ''
    return str(detail)


def _error_message(exc: BaseException, default: str) -> str:
    message = getattr(exc, 'msg', None) or getattr(exc, 'message', None) or str(exc)
    return str(message) if message else default


class GradesAPIView(APIView):
    """Auth pairing, person resolution and ``{code, message}`` errors."""

    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if isinstance(exc, ApiError):
            data = {'code': exc.code, 'message': exc.message}
        elif isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            missing = _first_error(response.data) == (
                'Authentication credentials were not provided')
            data = {
                'code': 'not_authenticated' if missing else 'invalid_token',
                'message': '请先登录。' if missing else '登录状态无效或已过期。',
            }
        elif isinstance(exc, PermissionDenied):
            data = {'code': 'permission_denied',
                    'message': _first_error(response.data) or '无权执行此操作。'}
        elif isinstance(exc, NotFound):
            data = {'code': 'not_found',
                    'message': _first_error(response.data) or '请求的内容不存在。'}
        elif isinstance(exc, ValidationError):
            data = {'code': 'validation_error',
                    'message': _first_error(response.data) or '请求参数有误。'}
        else:
            code = 'internal_error' if response.status_code >= 500 else str(
                getattr(exc, 'default_code', 'error'))
            data = {'code': code,
                    'message': _first_error(response.data) or '请求失败。'}
        response.data = data
        return response

    def get_person(self, request) -> NaturalPerson:
        """The caller's ``NaturalPerson``; 403 for organization accounts."""
        user = request.user
        if not (user.is_valid() and user.is_person()):
            raise PermissionDenied('请使用个人账号查看成绩。')
        try:
            return NaturalPerson.objects.get_by_user(user)
        except NaturalPerson.DoesNotExist:
            raise PermissionDenied('当前账号没有对应的个人信息。')


_ERROR_RESPONSES = {
    401: OpenApiResponse(response=GradesErrorSerializer, description='未登录或登录失效'),
    403: OpenApiResponse(response=GradesErrorSerializer, description='非个人账号或无权限'),
}


class GradesView(GradesAPIView):
    """
    ``GET``: the caller's stored grades (requires ``consent_grades``);
    ``DELETE``: wipe the caller's stored grades. Reads / deletes
    ``GradeRecord`` rows of the caller only.
    """

    @extend_schema(
        summary='查询已存储的成绩',
        description=(
            '返回平台已存储的成绩（需先在 /api/v2/pku/consents/ 开启成绩授权）。'
            '未绑定北大账号时 404 NOT_BOUND；未授权时 403 CONSENT_REQUIRED；'
            '已授权但尚未同步时返回空列表且 stored=false。'
        ),
        responses={
            200: GradesOutSerializer,
            403: OpenApiResponse(
                response=GradesErrorSerializer,
                description='非个人账号（permission_denied）/ CONSENT_REQUIRED'),
            404: OpenApiResponse(response=GradesErrorSerializer,
                                 description='NOT_BOUND'),
            401: _ERROR_RESPONSES[401],
        },
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        account = get_binding(request.user)
        if account is None:
            raise ApiError('NOT_BOUND', '尚未绑定北大账号。', status.HTTP_404_NOT_FOUND)
        if not account.consent_grades:
            raise ApiError('CONSENT_REQUIRED', '请先同意平台存储你的成绩数据。',
                           status.HTTP_403_FORBIDDEN)
        terms = services.stored_terms(person)
        return Response(services.grades_payload(
            terms, stored=bool(terms),
            fetched_at=services.last_fetched_at(person),
        ))

    @extend_schema(
        summary='删除已存储的成绩',
        description='删除平台存储的全部成绩记录；没有记录时同样返回 204。授权状态不变。',
        responses={204: OpenApiResponse(description='已删除'), **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def delete(self, request):
        person = self.get_person(request)
        services.delete_stored(person)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SyncView(GradesAPIView):
    """
    ``POST sync/``: fetch the live score list through the stored portal
    session and return it; when the binding carries ``consent_grades`` the
    rows are also stored (``stored: true``). Mutates ``GradeRecord`` rows
    of the caller and, through ``pku_account.services``, the session /
    ``last_sync_at`` bookkeeping of the binding.
    """

    @extend_schema(
        summary='从北大门户同步成绩',
        description=(
            '使用已有的门户会话拉取全部成绩并返回；已开启成绩授权时同时存储'
            '（stored=true），否则仅展示不存储。会话不可用或已过期时返回 409 '
            'PKU_LOGIN_REQUIRED，需重新登录 /api/v2/pku/login/。'
        ),
        request=None,
        responses={
            200: GradesOutSerializer,
            400: OpenApiResponse(response=GradesErrorSerializer,
                                 description='PARSE_FAILED'),
            404: OpenApiResponse(response=GradesErrorSerializer,
                                 description='NOT_BOUND'),
            409: OpenApiResponse(response=GradesErrorSerializer,
                                 description='PKU_LOGIN_REQUIRED'),
            503: OpenApiResponse(response=GradesErrorSerializer,
                                 description='PORTAL_DISABLED / PORTAL_UNREACHABLE'),
            **_ERROR_RESPONSES,
        },
        tags=TAGS,
    )
    def post(self, request):
        person = self.get_person(request)
        try:
            terms, account = services.fetch_scores(request.user)
        except NotBound as exc:
            raise ApiError('NOT_BOUND', _error_message(exc, '尚未绑定北大账号。'),
                           status.HTTP_404_NOT_FOUND)
        except SessionUnavailable:
            raise ApiError('PKU_LOGIN_REQUIRED', '门户登录状态失效，请重新登录。',
                           status.HTTP_409_CONFLICT)
        except PortalSessionExpired:
            raise ApiError('PKU_LOGIN_REQUIRED', '门户登录状态已过期，请重新登录。',
                           status.HTTP_409_CONFLICT)
        except PortalDisabled as exc:
            raise ApiError('PORTAL_DISABLED', _error_message(exc, '北大门户功能未启用。'),
                           status.HTTP_503_SERVICE_UNAVAILABLE)
        except PortalUnreachable as exc:
            logger.warning('grade sync of user #%s failed: portal unreachable',
                           request.user.pk)
            raise ApiError('PORTAL_UNREACHABLE',
                           _error_message(exc, '暂时无法连接北大门户，请稍后再试。'),
                           status.HTTP_503_SERVICE_UNAVAILABLE)
        except services.ScoresUnavailable as exc:
            raise ApiError('PARSE_FAILED', _error_message(exc, '门户未返回成绩数据。'),
                           status.HTTP_400_BAD_REQUEST)
        # mark_session_ok stamped last_sync_at with the fetch time.
        fetched_at = account.last_sync_at or datetime.now()
        stored = False
        if account.consent_grades:
            stored = services.store_scores(person, terms, fetched_at) > 0
        return Response(services.grades_payload(
            terms, stored=stored, fetched_at=fetched_at))
