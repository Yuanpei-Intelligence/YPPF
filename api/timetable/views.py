"""
REST APIs of the timetable for the WeChat mini-program.
Contract: ``timetable/README.md`` §4.6 (§6.1 subscribe messages, §6.3
course catalog, §6.5 agenda, §8 catalog links and quick add, scoped edits
and overrides, tags and the sources legend, share assets; §10 term
overview). Mounted at ``/api/v2/timetable/``.

Every endpoint requires a mini-program JWT (``WxJWTAuthentication`` +
``IsAuthenticated``) and a personal account; organization accounts get 403.
Errors are ``{code, message}`` bodies with the HTTP status carrying the
semantics (400 input, 401 identity, 403 permission, 404 absence, 409 state
conflict, 429 locked, 503 feature unavailable).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from functools import partial
from types import SimpleNamespace

from django.db import transaction
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
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
from api.config import get_subscribe_template
from api.timetable.serializers import (
    AgendaQuerySerializer,
    AgendaSerializer,
    CatalogAddSerializer,
    CatalogEntrySerializer,
    CatalogQuerySerializer,
    DryRunResponseSerializer,
    EntryInSerializer,
    EntryScopeSerializer,
    EntrySerializer,
    ErrorSerializer,
    IcsSerializer,
    ImportOutSerializer,
    ImportPortalSerializer,
    ImportTextSerializer,
    OverviewSerializer,
    SettingsOutSerializer,
    SettingsSerializer,
    ShareAssetsSerializer,
    SubscribeGrantOutSerializer,
    SubscribeGrantSerializer,
    SubscribeTemplatesSerializer,
    TermsResponseSerializer,
    WeekQuerySerializer,
    WeekViewSerializer,
)
from timetable import catalog, reminders, services, share
from timetable.calendar import calendar_for, calendars_for
from timetable.exams import exams_for_entries
from timetable.models import (
    AcademicTerm,
    CourseCatalogEntry,
    TimetableEntry,
    TimetableEntryOverride,
)
from timetable.overrides import resolve_week

__all__ = [
    'ApiError',
    'TermsView',
    'WeekView',
    'AgendaView',
    'OverviewView',
    'EntryViewSet',
    'ImportPortalView',
    'ImportTextView',
    'SettingsView',
    'IcsView',
    'IcsRotateView',
    'SubscribeTemplatesView',
    'SubscribeGrantView',
    'CatalogView',
    'CatalogAddView',
    'ShareAssetsView',
]

logger = logging.getLogger(__name__)

TAGS = ['课表']
# Body keys of PATCH entries/<id>/ that belong to the scope, not the entry.
_SCOPE_KEYS = ('scope', 'week', 'canceled')
# API keys that need scope='all' (README §8.2): row-only annotations and
# the recurrence of the entry.
_ALL_SCOPE_KEYS = ('hidden', 'role', 'category', 'catalog_id',
                   'week_start', 'week_end', 'parity')
# Recurrence keys imported entries cannot change (re-import instead).
_RECURRENCE_KEYS = ('week_start', 'week_end', 'parity')


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


def _field_errors(detail) -> dict[str, list[dict[str, str]]]:
    """Canonical field errors: ``{field: [{code, message}]}`` (same shape as
    the platform-wide envelope of ``api/exceptions.py``)."""
    if not isinstance(detail, dict):
        return {}
    errors: dict[str, list[dict[str, str]]] = {}
    for name, value in detail.items():
        if name == 'detail':
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        errors[str(name)] = [
            {'code': str(getattr(item, 'code', None) or 'invalid'), 'message': str(item)}
            for item in values]
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
        if not (user.is_valid() and user.is_person()):
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


def _entry_queryset(person):
    # Entries with everything the Entry payload needs.
    return (TimetableEntry.objects.filter(person=person)
            .select_related('term', 'catalog_entry').prefetch_related('overrides'))


def _entry_payloads(entries, term: AcademicTerm | None = None) -> list[dict]:
    """``Entry[]`` of entries of one term with one exam lookup for all of them."""
    entries = list(entries)
    if not entries:
        return []
    if term is None:
        term = entries[0].term
    exams = exams_for_entries(term, entries)
    return EntrySerializer(entries, many=True, context={'exams': exams}).data


def _entry_payload(entry: TimetableEntry) -> dict:
    return _entry_payloads([entry], entry.term)[0]


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
        terms = list(AcademicTerm.objects.filter(is_active=True).order_by('-week1_monday'))
        calendars = calendars_for(terms)
        if current is not None and current.code not in calendars:
            calendars[current.code] = calendar_for(current)
        return Response({
            'current': (services.term_payload(current, calendar=calendars[current.code])
                        if current is not None else None),
            'terms': [services.term_payload(term, calendar=calendars[term.code])
                      for term in terms],
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


class AgendaView(TimetableAPIView):
    """Consecutive days of the merged timetable, across term boundaries."""

    @extend_schema(
        summary='日程',
        description=(
            f'从 from 起连续 days 天的日程（缺省今天起 7 天，最多 {services.AGENDA_MAX_DAYS} 天，'
            '超出按上限截断）。跨学期：不在任何学期内的日期 term/week 为 null 且没有课表条目，'
            '书院课 / 活动 / 预约照常显示；每天带校历标签。'
        ),
        parameters=[
            OpenApiParameter('from', OpenApiTypes.DATE, OpenApiParameter.QUERY, required=False,
                             description='起始日期 YYYY-MM-DD，缺省今天'),
            OpenApiParameter('days', int, OpenApiParameter.QUERY, required=False,
                             description=f'天数，缺省 7，最多 {services.AGENDA_MAX_DAYS}'),
        ],
        responses={
            200: AgendaSerializer,
            400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
            **_ERROR_RESPONSES,
        },
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        query = AgendaQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start = query.validated_data.get('from') or date.today()
        return Response(services.agenda(person, start, query.validated_data['days']))


class OverviewView(TimetableAPIView):
    """
    Every weekly slot and exam of one term for the share poster
    (``services.term_overview``, README §10). Read-only; same person and
    term rules as ``WeekView``.
    """

    @extend_schema(
        summary='学期总览',
        description=(
            '整个学期（第 1..total_weeks 周）的课表，供海报使用。学校课表、书院课和自定义条目'
            '按（来源、条目、星期、起止时间、地点、名称）合并为时段，给出上课周次 weeks、'
            '周次文字 weeks_text（第3周 / 1-16周 / 1-15周 单周 / 2-16周 双周 / 1-8,10-16周）'
            '和单双周 parity。放假、停课复习考试等校历停课不在周次中留空；按周停课会留空，'
            '按周调整时间 / 星期 / 地点的那几次单独成一个时段。考试去重后列在 exams；'
            '活动与地下室预约不列出。与周视图一样遵循来源开关、隐藏标签和隐藏条目。'
            'term 缺省为当前学期。'
        ),
        parameters=[
            OpenApiParameter('term', str, OpenApiParameter.QUERY, required=False,
                             description='学期代码，如 26-27-1'),
        ],
        responses={
            200: OverviewSerializer,
            404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
            **_ERROR_RESPONSES,
        },
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        term = self.resolve_term(request.query_params.get('term'))
        return Response(services.term_overview(person, term))


class EntryViewSet(TimetableAPIMixin, viewsets.ViewSet):
    """
    Stored entries of the caller. Manual entries are fully editable;
    imported (portal/paste) entries take the student's annotations on the
    row and every other edit as an override (README §8.2), so re-imports
    keep them. Hidden entries are listed so they can be un-hidden.
    """

    def get_queryset(self, request):
        person = self.get_person(request)
        return _entry_queryset(person)

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
        return Response(_entry_payloads(entries, term))

    @extend_schema(
        summary='条目详情',
        description='一条存储条目的完整信息：目录课程、按周修改记录、匹配到的考试。',
        responses={200: EntrySerializer,
                   404: OpenApiResponse(response=ErrorSerializer, description='条目不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def retrieve(self, request, pk=None):
        return Response(_entry_payload(self.get_entry(request, pk)))

    @extend_schema(
        summary='新建手动条目',
        description='可带 catalog_id（同学期课程目录行）、role、category、tag。',
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
        return Response(_entry_payload(self.get_entry(request, entry.pk)),
                        status=status.HTTP_201_CREATED)

    @extend_schema(
        summary='修改条目',
        description=(
            'scope=all（缺省）：手动条目直接修改；任何来源的 hidden/color/tag/role/category/'
            'catalog_id 直接修改；导入条目的其它字段写入整个周次范围的修改记录，重新导入后仍然保留。'
            'scope=single/following 需给出 week（在条目周次范围内），把给出的字段（可含 canceled）'
            '写入该周 / 该周及以后的修改记录。hidden/role/category/catalog_id 与周次范围、'
            '单双周只能在 scope=all 下修改（400 errors.scope）。'
        ),
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
        scope_serializer = EntryScopeSerializer(
            data={key: data[key] for key in _SCOPE_KEYS if key in data},
            context={'entry': entry})
        scope_serializer.is_valid(raise_exception=True)
        scope = scope_serializer.validated_data.get('scope') or 'all'
        week = scope_serializer.validated_data.get('week')
        canceled = scope_serializer.validated_data.get('canceled')
        body = {key: value for key, value in data.items() if key not in _SCOPE_KEYS}
        if scope != 'all':
            blocked = [key for key in body if key in _ALL_SCOPE_KEYS]
            if blocked:
                raise ValidationError(
                    {'scope': f'{"、".join(blocked)} 只能对整门课程（scope=all）修改'})
        elif not entry.is_manual():
            blocked = [key for key in body if key in _RECURRENCE_KEYS]
            if blocked:
                raise ValidationError(
                    {blocked[0]: '导入的课程不能修改周次范围和单双周，请重新导入'})
        if scope == 'all' and entry.is_manual():
            base = entry
        else:
            base = _edit_base(entry, scope, week)
        serializer = EntryInSerializer(base, data=body, partial=True,
                                       context={'term': entry.term})
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop('term', None)
        if values or canceled is not None:
            try:
                services.update_entry(entry, values, scope=scope, week=week,
                                      canceled=canceled)
            except ValueError as exc:
                raise ValidationError({'scope': str(exc)})
        return Response(_entry_payload(self.get_entry(request, pk)))

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

    @extend_schema(
        operation_id='v2_timetable_entries_overrides_reset',
        summary='恢复全部修改',
        description='删除该条目的所有按周修改记录（恢复导入/原始状态）。',
        responses={204: OpenApiResponse(description='已恢复'),
                   404: OpenApiResponse(response=ErrorSerializer, description='条目不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def reset_overrides(self, request, pk=None):
        entry = self.get_entry(request, pk)
        TimetableEntryOverride.objects.filter(entry=entry).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id='v2_timetable_entries_overrides_destroy',
        summary='恢复一条修改',
        description='删除该条目的一条按周修改记录（恢复该次 / 该段）。',
        responses={204: OpenApiResponse(description='已恢复'),
                   404: OpenApiResponse(response=ErrorSerializer,
                                        description='条目或修改记录不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def delete_override(self, request, pk=None, oid=None):
        entry = self.get_entry(request, pk)
        deleted, _ = TimetableEntryOverride.objects.filter(entry=entry, pk=oid).delete()
        if not deleted:
            raise ApiError('timetable.override_not_found', '该修改记录不存在。',
                           status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _edit_base(entry: TimetableEntry, scope: str, week: int | None) -> SimpleNamespace:
    # The values a scoped edit is validated against: the entry with the
    # override of the same range (if any) applied, so a partial body is
    # checked against what the student currently sees for that range.
    if scope == 'single':
        bounds = (week, week)
    elif scope == 'following':
        bounds = (week, None)
    else:
        bounds = (None, None)
    override = (TimetableEntryOverride.objects
                .filter(entry=entry, week_start=bounds[0], week_end=bounds[1])
                .order_by('id').first())
    base = SimpleNamespace(**{name: getattr(entry, name)
                              for name in EntryInSerializer._ENTRY_FIELDS})
    if override is not None:
        resolved = resolve_week(entry, [override], week or entry.week_start, entry.term)
        for name, value in resolved.values.items():
            setattr(base, name, value)
    return base


class _PkuBridge:
    """The names of the ``pku_account`` integration (``timetable/README.md`` §3)."""

    def __init__(self, services_module, iaaa_module, portal_module, elective_module):
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
        self.ElectiveClient = elective_module.ElectiveClient


def _load_pku() -> _PkuBridge:
    # Imported lazily: the pku_account app is optional and independent.
    from pku_account import services as pku_services
    from pku_account.extern import elective, iaaa, portal
    return _PkuBridge(pku_services, iaaa, portal, elective)


def _error_message(exc: BaseException, default: str) -> str:
    message = getattr(exc, 'msg', None) or getattr(exc, 'message', None) or str(exc)
    return str(message) if message else default


def _elective_results(pku: _PkuBridge, username: str,
                      password: str) -> tuple[str | None, str]:
    """
    The elective 选课结果 page for the fallback of ``services.import_portal``,
    as ``(html or None, outcome)``. A failure (outside the selection period,
    a second factor, a site change) never fails the import by itself: it is
    logged by exception class only and named in the ``ImportLog`` message.
    """
    try:
        client = pku.ElectiveClient.login(username, password)
        return client.get_results_html(), 'ok'
    except pku.IaaaError as exc:
        outcome = f'{type(exc).__name__} {getattr(exc, "code", "")}'.strip()
    except (pku.PortalUnreachable, pku.PortalSessionExpired) as exc:
        outcome = type(exc).__name__
    logger.warning('elective fallback failed: %s', outcome)
    return None, outcome


class ImportPortalView(TimetableAPIView):
    """
    Fetch the term's timetable from the PKU portal and store it. With
    credentials, the elective 选课结果 page stands in for an empty course
    table of the current or upcoming term (``services.import_portal``).
    """

    @extend_schema(
        summary='从北大门户导入课表',
        description=(
            '给出 username+password 时先登录并绑定（隐含 consent_timetable），'
            '否则使用已有的门户会话。会话不可用时返回 409 PKU_LOGIN_REQUIRED；'
            '未同意使用课表数据时返回 403 CONSENT_REQUIRED；IAAA 错误码同 /api/v2/pku/。'
            '给出 username+password 且当前（或即将开始的）学期门户课表为空时，改用同一账号'
            '登录选课系统导入「选课结果」（来源仍为 portal，之后的门户课表导入会替换它）；'
            '选课系统也取不到课程时与课表为空相同（400 PARSE_FAILED）。'
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
        # With credentials the elective 选课结果 page may stand in for an
        # empty course table; services.import_portal decides when.
        elective_results = (partial(_elective_results, pku, username, password)
                            if username and password else None)
        try:
            result = services.import_portal(person, term, raw,
                                            elective_results=elective_results)
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
        description='含 hidden_tags、show_exams，以及只读的 sources（来源图例及其开关字段）'
                    '和 tags（本人所有条目的标签）。',
        responses={200: SettingsOutSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        settings = services.get_or_create_settings(person)
        return Response(services.settings_payload(person, settings))

    @extend_schema(
        summary='修改课表设置',
        description='hidden_tags 会去重、去空白，每个标签最长 24 字。',
        request=SettingsSerializer,
        responses={200: SettingsOutSerializer,
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
        return Response(services.settings_payload(person, settings))


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


class SubscribeTemplatesView(TimetableAPIView):
    """Subscribe-message template ids the client may request grants for."""

    @extend_schema(
        summary='订阅消息模板',
        description='各模板的 template_id；未配置时为 null，'
                    '此时客户端不应调用 wx.requestSubscribeMessage。',
        responses={200: SubscribeTemplatesSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        self.get_person(request)
        data = {}
        for key in reminders.subscribe_template_keys():
            template = get_subscribe_template(key)
            data[key] = {'template_id': template['id'] if template else None}
        return Response(data)


class SubscribeGrantView(TimetableAPIView):
    """Record accepted subscribe-message grants (``wx.requestSubscribeMessage``)."""

    @extend_schema(
        summary='登记订阅消息授权',
        description='每次 wx.requestSubscribeMessage 返回 accept 后调用；'
                    '服务端累计并按 subscribe_quota_cap 封顶，count 缺省为 1。',
        request=SubscribeGrantSerializer,
        responses={200: SubscribeGrantOutSerializer,
                   400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def post(self, request):
        self.get_person(request)
        serializer = SubscribeGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        quota = reminders.grant_subscribe_quota(
            request.user, data['template_key'], data['count'])
        return Response(SubscribeGrantOutSerializer({
            'template_key': quota.template_key,
            'count': quota.count,
        }).data)


class CatalogView(TimetableAPIView):
    """Search the course catalog of a term (manual-entry prefill, quick add)."""

    @extend_schema(
        summary='课程目录检索',
        description='按课程名 / 课程号 / 教师模糊匹配（icontains），最多 20 条；'
                    'q 为空时返回空列表。term 缺省为当前学期。added 表示本人在该学期'
                    '已有关联到这一行的条目。',
        parameters=[
            OpenApiParameter('term', str, OpenApiParameter.QUERY, required=False,
                             description='学期代码'),
            OpenApiParameter('q', str, OpenApiParameter.QUERY, required=False,
                             description='关键词'),
        ],
        responses={200: CatalogEntrySerializer(many=True),
                   400: OpenApiResponse(response=ErrorSerializer, description='参数错误'),
                   404: OpenApiResponse(response=ErrorSerializer, description='学期不存在'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        person = self.get_person(request)
        query = CatalogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        term = self.resolve_term(query.validated_data.get('term'))
        rows = list(catalog.search_catalog(term, query.validated_data.get('q', '')))
        added: set[int] = set()
        if rows:
            added = set(TimetableEntry.objects.filter(
                person=person, term=term, catalog_entry__in=rows,
            ).values_list('catalog_entry_id', flat=True))
        serializer = CatalogEntrySerializer(rows, many=True, context={'added': added})
        return Response(serializer.data)


class CatalogAddView(TimetableAPIView):
    """Quick-add a catalog row (旁听 by default) to the caller's timetable."""

    @extend_schema(
        summary='从课程目录加入课表',
        description=(
            '为课程目录行的每个（选中的）时段建一条手动条目并关联到该行，缺省身份为旁听。'
            '404 timetable.catalog_not_found：该学期没有这一行；'
            '409 timetable.catalog_already_added：已有关联条目；'
            '400 timetable.catalog_no_slots：该行没有可解析的上课时间；'
            '400 errors.slots：时段序号越界。'
        ),
        request=CatalogAddSerializer,
        responses={201: EntrySerializer(many=True),
                   400: OpenApiResponse(
                       response=ErrorSerializer,
                       description='timetable.catalog_no_slots / errors.slots'),
                   404: OpenApiResponse(
                       response=ErrorSerializer,
                       description='timetable.catalog_not_found / 学期不存在'),
                   409: OpenApiResponse(
                       response=ErrorSerializer,
                       description='timetable.catalog_already_added'),
                   **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def post(self, request, pk=None):
        person = self.get_person(request)
        serializer = CatalogAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        term = self.resolve_term(data.get('term'))
        row = CourseCatalogEntry.objects.filter(pk=pk, term=term).first()
        if row is None:
            raise ApiError('timetable.catalog_not_found', '课程目录中没有该学期的这门课。',
                           status.HTTP_404_NOT_FOUND)
        try:
            entries = services.quick_add_from_catalog(
                person, term, row, role=data['role'], slot_indices=data.get('slots'))
        except ValueError as exc:
            raise ValidationError({'slots': f'时段序号越界（{exc}）'})
        except services.CatalogAddError as exc:
            if exc.code == services.CatalogAddError.ALREADY_ADDED:
                raise ApiError(exc.code, exc.message, status.HTTP_409_CONFLICT)
            raise ApiError(exc.code, exc.message, status.HTTP_400_BAD_REQUEST)
        entries = list(_entry_queryset(person)
                       .filter(pk__in=[entry.pk for entry in entries])
                       .order_by('weekday', 'start_section', 'start_time', 'id'))
        return Response(_entry_payloads(entries, term), status=status.HTTP_201_CREATED)


class ShareAssetsView(TimetableAPIView):
    """QR assets of the timetable poster (README §8.5)."""

    @extend_schema(
        summary='海报分享素材',
        description='小程序码（wxacode.getUnlimited，服务端缓存 30 天）、公众号二维码和口号；'
                    '无法生成时对应字段为 null，不报错。',
        responses={200: ShareAssetsSerializer, **_ERROR_RESPONSES},
        tags=TAGS,
    )
    def get(self, request):
        self.get_person(request)
        return Response(ShareAssetsSerializer(share.share_assets()).data)
