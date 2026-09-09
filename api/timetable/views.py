"""
REST APIs of the timetable for the WeChat mini-program.
Contract: ``timetable/README.md`` §4.6. Mounted at ``/api/v2/timetable/``.

Every endpoint requires a mini-program JWT (``WxJWTAuthentication`` +
``IsAuthenticated``) and a personal account; organization accounts get 403.
Errors are ``{code, message}`` bodies with the HTTP status carrying the
semantics (400 input, 401 identity, 403 permission, 404 absence, 409 state
conflict, 429 locked, 503 feature unavailable).
"""
from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.urls import reverse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
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

from utils.http.utils import build_full_url
from app.models import NaturalPerson
from api.authentication import WxJWTAuthentication
from api.timetable.serializers import (
    DryRunResponseSerializer,
    EntryInSerializer,
    EntrySerializer,
    ErrorSerializer,
    IcsSerializer,
    ImportOutSerializer,
    ImportPortalSerializer,
    ImportTextSerializer,
    SettingsSerializer,
    TermsResponseSerializer,
    WeekQuerySerializer,
    WeekViewSerializer,
)
from timetable import services
from timetable.models import AcademicTerm, TimetableEntry

__all__ = [
    'ApiError',
    'TermsView',
    'WeekView',
    'EntryViewSet',
    'ImportPortalView',
    'ImportTextView',
    'SettingsView',
    'IcsView',
    'IcsRotateView',
]

logger = logging.getLogger(__name__)

TAGS = ['课表']


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


def _field_errors(detail) -> dict[str, list[str]]:
    if not isinstance(detail, dict):
        return {}
    errors: dict[str, list[str]] = {}
    for name, value in detail.items():
        if name == 'detail':
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        errors[str(name)] = [str(item) for item in values]
    return errors


class TimetableAPIMixin:
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
                    'message': _first_error(response.data) or '请求参数有误。',
                    'errors': _field_errors(response.data)}
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
        if not user.is_person():
            raise PermissionDenied('请使用个人账号访问课表。')
        try:
            return NaturalPerson.objects.get_by_user(user)
        except NaturalPerson.DoesNotExist:
            raise PermissionDenied('当前账号没有对应的个人信息。')

    def resolve_term(self, code: str | None) -> AcademicTerm:
        """The active term with ``code``, or the default term when blank."""
        code = (code or '').strip()
        if code:
            term = AcademicTerm.objects.filter(code=code, is_active=True).first()
            if term is None:
                raise ApiError('TERM_NOT_FOUND', '未找到该学期。', status.HTTP_404_NOT_FOUND)
            return term
        term = services.default_term()
        if term is None:
            raise ApiError('NO_CURRENT_TERM', '当前没有可用的学期，请联系管理员。',
                           status.HTTP_404_NOT_FOUND)
        return term


class TimetableAPIView(TimetableAPIMixin, APIView):
    pass


_ERROR_RESPONSES = {
    401: OpenApiResponse(response=ErrorSerializer, description='未登录或登录失效'),
    403: OpenApiResponse(response=ErrorSerializer, description='非个人账号或无权限'),
}


class TermsView(TimetableAPIView):
    """Active terms and the default (current or upcoming) term."""

    @extend_schema(
        summary='学期列表',
        description='所有启用的学期，以及当前（或即将开始的）学期。',
        responses={200: TermsResponseSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        self.get_person(request)
        current = services.default_term()
        terms = AcademicTerm.objects.filter(is_active=True).order_by('-week1_monday')
        return Response({
            'current': services.term_payload(current) if current is not None else None,
            'terms': [services.term_payload(term) for term in terms],
        })


class WeekView(TimetableAPIView):
    """One teaching week of the merged timetable."""

    @extend_schema(
        summary='周视图',
        description='合并所有启用来源的一周课表；term/week 缺省为当前学期/本周，'
                    'week 会被限制在 1..total_weeks。',
        parameters=[
            OpenApiParameter('term', str, OpenApiParameter.QUERY, required=False,
                             description='学期代码，如 26-27-1'),
            OpenApiParameter('week', int, OpenApiParameter.QUERY, required=False,
                             description='教学周'),
        ],
        responses={
            200: WeekViewSerializer,
            400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
            404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
            **_ERROR_RESPONSES,
        },
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        query = WeekQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        term = self.resolve_term(query.validated_data.get('term'))
        week = query.validated_data.get('week')
        if week is None:
            week = term.week_of(datetime.now().date())
        return Response(services.week_view(person, term, term.clamp_week(week)))


class EntryViewSet(TimetableAPIMixin, viewsets.ViewSet):
    """
    Stored entries of the caller. Manual entries are fully editable; imported
    (portal/paste) entries can only be hidden/unhidden and are replaced by the
    next import.
    """

    def get_queryset(self, request):
        person = self.get_person(request)
        return TimetableEntry.objects.filter(person=person).select_related('term')

    def get_entry(self, request, pk) -> TimetableEntry:
        entry = self.get_queryset(request).filter(pk=pk).first()
        if entry is None:
            raise NotFound('课表条目不存在。')
        return entry

    @extend_schema(
        summary='条目列表',
        description='某学期的全部存储条目（含隐藏的）。term 缺省为当前学期。',
        parameters=[
            OpenApiParameter('term', str, OpenApiParameter.QUERY, required=False,
                             description='学期代码'),
        ],
        responses={200: EntrySerializer(many=True),
                   404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def list(self, request):
        queryset = self.get_queryset(request)
        term = self.resolve_term(request.query_params.get('term'))
        entries = queryset.filter(term=term).order_by(
            'weekday', 'start_section', 'start_time', 'id')
        return Response(EntrySerializer(entries, many=True).data)

    @extend_schema(
        summary='新建手动条目',
        request=EntryInSerializer,
        responses={201: EntrySerializer,
                   400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
                   404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def create(self, request):
        person = self.get_person(request)
        term = self.resolve_term(request.data.get('term') if isinstance(request.data, dict) else None)
        serializer = EntryInSerializer(data=request.data, context={'term': term})
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        fields.pop('term', None)
        entry = TimetableEntry.objects.create(
            person=person, term=term, source=TimetableEntry.Source.MANUAL,
            external_key=TimetableEntry.new_manual_key(), **fields)
        return Response(EntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary='修改条目',
        description='hidden 对任何来源都可修改；其它字段仅限手动条目。',
        request=EntryInSerializer,
        responses={200: EntrySerializer,
                   400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
                   404: OpenApiResponse(response=ErrorSerializer, description='条目不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def partial_update(self, request, pk=None):
        entry = self.get_entry(request, pk)
        data = request.data if isinstance(request.data, dict) else {}
        data = {key: value for key, value in data.items() if key != 'term'}
        if not entry.is_manual() and any(key != 'hidden' for key in data):
            raise PermissionDenied('导入的课程只能隐藏或显示，请重新导入以修改内容。')
        serializer = EntryInSerializer(
            entry, data=data, partial=True, context={'term': entry.term})
        serializer.is_valid(raise_exception=True)
        changed = list(serializer.validated_data)
        if changed:
            for name, value in serializer.validated_data.items():
                setattr(entry, name, value)
            entry.save(update_fields=changed + ['updated_at'])
        return Response(EntrySerializer(entry).data)

    @extend_schema(
        summary='删除手动条目',
        responses={204: OpenApiResponse(description='已删除'),
                   404: OpenApiResponse(response=ErrorSerializer, description='条目不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def destroy(self, request, pk=None):
        entry = self.get_entry(request, pk)
        if not entry.is_manual():
            raise PermissionDenied('导入的课程不能删除，可以将其隐藏。')
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _PkuBridge:
    """The names of the ``pku_account`` integration (``timetable/README.md`` §3)."""

    def __init__(self, services_module, iaaa_module, portal_module):
        self.login_and_bind = services_module.login_and_bind
        self.get_binding = services_module.get_binding
        self.get_client = services_module.get_client
        self.mark_session_ok = services_module.mark_session_ok
        self.invalidate_session = services_module.invalidate_session
        self.PortalDisabled = services_module.PortalDisabled
        self.AccountLocked = services_module.AccountLocked
        self.AlreadyBoundElsewhere = services_module.AlreadyBoundElsewhere
        self.NotBound = services_module.NotBound
        self.SessionUnavailable = services_module.SessionUnavailable
        self.IaaaError = iaaa_module.IaaaError
        self.OtpRequired = iaaa_module.OtpRequired
        self.CaptchaRequired = iaaa_module.CaptchaRequired
        self.PortalUnreachable = iaaa_module.PortalUnreachable
        self.PortalSessionExpired = portal_module.PortalSessionExpired


def _load_pku() -> _PkuBridge:
    # Imported lazily: the pku_account app is optional and independent.
    from pku_account import services as pku_services
    from pku_account.extern import iaaa, portal
    return _PkuBridge(pku_services, iaaa, portal)


def _error_message(exc: BaseException, default: str) -> str:
    message = getattr(exc, 'msg', None) or getattr(exc, 'message', None) or str(exc)
    return str(message) if message else default


class ImportPortalView(TimetableAPIView):
    """Fetch the term's timetable from the PKU portal and store it."""

    @extend_schema(
        summary='从北大门户导入课表',
        description=(
            '给出 username+password 时先登录并绑定（隐含 consent_timetable），'
            '否则使用已有的门户会话。会话不可用时返回 409 PKU_LOGIN_REQUIRED；'
            '未同意使用课表数据时返回 403 CONSENT_REQUIRED；IAAA 错误码同 /api/v2/pku/。'
        ),
        request=ImportPortalSerializer,
        responses={
            200: ImportOutSerializer,
            400: OpenApiResponse(response=ErrorSerializer,
                                 description='IAAA_ERROR / OTP_REQUIRED / CAPTCHA_REQUIRED / PARSE_FAILED'),
            403: OpenApiResponse(response=ErrorSerializer, description='CONSENT_REQUIRED'),
            404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
            409: OpenApiResponse(response=ErrorSerializer,
                                 description='PKU_LOGIN_REQUIRED / ALREADY_BOUND_ELSEWHERE'),
            429: OpenApiResponse(response=ErrorSerializer, description='LOCKED'),
            503: OpenApiResponse(response=ErrorSerializer,
                                 description='PORTAL_DISABLED / PORTAL_UNREACHABLE'),
            401: _ERROR_RESPONSES[401],
        },
        tags=TAGS,
    )
    def post(self, request):
        person = self.get_person(request)
        serializer = ImportPortalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        term = self.resolve_term(data.get('term'))
        try:
            pku = _load_pku()
        except (ImportError, AttributeError) as exc:
            logger.warning('pku_account integration unavailable: %s', exc)
            raise ApiError('PORTAL_DISABLED', '北大门户导入功能未启用。',
                           status.HTTP_503_SERVICE_UNAVAILABLE)
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''
        account = None
        try:
            if username and password:
                # consent_timetable is implied by importing with credentials.
                account = pku.login_and_bind(
                    request.user, username, password, consent_timetable=True)
            else:
                account = pku.get_binding(request.user)
                if account is None:
                    raise ApiError('PKU_LOGIN_REQUIRED', '请先登录北大门户账号。',
                                   status.HTTP_409_CONFLICT)
            if not getattr(account, 'consent_timetable', False):
                raise ApiError('CONSENT_REQUIRED', '请先同意使用门户课表数据。',
                               status.HTTP_403_FORBIDDEN)
            client = pku.get_client(request.user)
            raw = client.get_course_info(term.code)
        except pku.PortalUnreachable as exc:
            raise ApiError('PORTAL_UNREACHABLE',
                           _error_message(exc, '暂时无法连接北大门户，请稍后再试。'),
                           status.HTTP_503_SERVICE_UNAVAILABLE)
        except pku.OtpRequired as exc:
            raise ApiError('OTP_REQUIRED', _error_message(exc, '需要二次验证。'),
                           status.HTTP_400_BAD_REQUEST)
        except pku.CaptchaRequired as exc:
            raise ApiError('CAPTCHA_REQUIRED', _error_message(exc, '需要验证码。'),
                           status.HTTP_400_BAD_REQUEST)
        except pku.IaaaError as exc:
            raise ApiError('IAAA_ERROR', _error_message(exc, '北大账号登录失败。'),
                           status.HTTP_400_BAD_REQUEST)
        except pku.AccountLocked as exc:
            raise ApiError('LOCKED', _error_message(exc, '登录失败次数过多，请稍后再试。'),
                           status.HTTP_429_TOO_MANY_REQUESTS)
        except pku.AlreadyBoundElsewhere as exc:
            raise ApiError('ALREADY_BOUND_ELSEWHERE',
                           _error_message(exc, '该北大账号已绑定其他用户。'),
                           status.HTTP_409_CONFLICT)
        except pku.PortalDisabled as exc:
            raise ApiError('PORTAL_DISABLED', _error_message(exc, '北大门户导入功能未启用。'),
                           status.HTTP_503_SERVICE_UNAVAILABLE)
        except (pku.SessionUnavailable, pku.NotBound):
            raise ApiError('PKU_LOGIN_REQUIRED', '门户登录状态失效，请重新登录。',
                           status.HTTP_409_CONFLICT)
        except pku.PortalSessionExpired:
            if account is not None:
                pku.invalidate_session(account, 'expired')
            raise ApiError('PKU_LOGIN_REQUIRED', '门户登录状态已过期，请重新登录。',
                           status.HTTP_409_CONFLICT)
        try:
            result = services.import_portal(person, term, raw)
        except services.TimetableImportError as exc:
            raise ApiError(exc.code, exc.message, status.HTTP_400_BAD_REQUEST)
        # synced=True also records PkuAccount.last_sync_at.
        pku.mark_session_ok(account, synced=True)
        return Response(ImportOutSerializer({
            'term': term.code,
            'created': result.created,
            'updated': result.updated,
            'removed': result.removed,
            'total': result.total,
        }).data)


class ImportTextView(TimetableAPIView):
    """Parse pasted text (portal HTML / elective table) and store it."""

    @extend_schema(
        summary='粘贴导入课表',
        description='dry_run 时仅返回解析结果 {format, blocks}，不写入。',
        request=ImportTextSerializer,
        responses={
            200: OpenApiResponse(
                response=ImportOutSerializer,
                description='导入结果；dry_run 时为 DryRunResponse'),
            400: OpenApiResponse(response=ErrorSerializer, description='参数错误 / PARSE_FAILED'),
            404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
            **_ERROR_RESPONSES,
        },
        tags=TAGS,
    )
    def post(self, request):
        person = self.get_person(request)
        serializer = ImportTextSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        term = self.resolve_term(data.get('term'))
        if data['dry_run']:
            fmt, blocks = services.parse_text(data['text'])
            return Response(DryRunResponseSerializer({
                'format': fmt,
                'blocks': [block.as_dict() for block in blocks],
            }).data)
        try:
            result = services.import_text(person, term, data['text'])
        except services.TimetableImportError as exc:
            raise ApiError(exc.code, exc.message, status.HTTP_400_BAD_REQUEST)
        return Response(ImportOutSerializer({
            'term': term.code,
            'created': result.created,
            'updated': result.updated,
            'removed': result.removed,
            'total': result.total,
        }).data)


class SettingsView(TimetableAPIView):
    """Timetable preferences of the caller."""

    @extend_schema(
        summary='课表设置',
        responses={200: SettingsSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        settings = services.get_or_create_settings(person)
        return Response(SettingsSerializer(settings).data)

    @extend_schema(
        summary='修改课表设置',
        request=SettingsSerializer,
        responses={200: SettingsSerializer,
                   400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def patch(self, request):
        person = self.get_person(request)
        settings = services.get_or_create_settings(person)
        serializer = SettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            serializer.save()
        return Response(SettingsSerializer(settings).data)


def _ics_payload(settings) -> dict:
    path = reverse('timetable:ics_feed', kwargs={'token': settings.ics_token})
    return {'url': build_full_url(path), 'token': str(settings.ics_token)}


class IcsView(TimetableAPIView):
    """The caller's private ICS feed URL."""

    @extend_schema(
        summary='ICS 订阅地址',
        responses={200: IcsSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        settings = services.get_or_create_settings(person)
        return Response(IcsSerializer(_ics_payload(settings)).data)


class IcsRotateView(TimetableAPIView):
    """Rotate the ICS token, invalidating the previous URL."""

    @extend_schema(
        summary='重置 ICS 订阅地址',
        request=None,
        responses={200: IcsSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def post(self, request):
        person = self.get_person(request)
        settings = services.get_or_create_settings(person)
        with transaction.atomic():
            settings.rotate_ics_token()
        return Response(IcsSerializer(_ics_payload(settings)).data)
