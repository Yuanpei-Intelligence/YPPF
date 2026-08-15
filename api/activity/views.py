"""
REST APIs for activity homepage data.
"""
from __future__ import annotations

from datetime import datetime

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)

from api.activity.checkin import do_checkin
from api.activity.serializers import (
    ActivityActionResultSerializer,
    ActivityCheckinRequestSerializer,
    ActivityDetailSerializer,
    ActivityErrorSerializer,
    ActivityHomepageSerializer,
    ActivityMessageSerializer,
)
from api.authentication import WxJWTAuthentication
from app.activity_utils import (
    ActivityException,
    apply_activity_for_person,
    withdraw_activity_for_person,
)
from app.models import Activity, Position
from app.utils import get_person_or_org
from generic.models import User


__all__ = ['ActivityViewSet']


def _first_error(detail) -> str:
    """Return the first human-readable message from a DRF error detail."""
    if isinstance(detail, dict):
        for value in detail.values():
            return _first_error(value)
        return ''
    if isinstance(detail, (list, tuple)):
        return _first_error(detail[0]) if detail else ''
    return str(detail)


def _field_errors(detail) -> dict[str, list[str]]:
    """Convert DRF field errors to the canonical string-list mapping."""
    if not isinstance(detail, dict):
        return {}
    errors: dict[str, list[str]] = {}
    for field, value in detail.items():
        if field == 'detail':
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        errors[str(field)] = [str(item) for item in values]
    return errors


class ActivityViewSet(viewsets.ViewSet):
    """
    ViewSet for activity homepage data.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    def handle_exception(self, exc):
        """Normalize errors from all activity endpoints."""
        response = super().handle_exception(exc)
        if isinstance(exc, AuthenticationFailed):
            raw_message = _first_error(response.data)
            missing = raw_message == (
                'Authentication credentials were not provided'
            )
            code = 'not_authenticated' if missing else 'invalid_token'
            message = (
                '请先登录。' if missing else '登录状态无效或已过期。'
            )
        elif isinstance(exc, PermissionDenied):
            code = 'permission_denied'
            message = _first_error(response.data) or '无权执行此操作。'
        elif isinstance(exc, NotFound):
            code = 'not_found'
            message = _first_error(response.data) or '请求的内容不存在。'
        elif isinstance(exc, ValidationError):
            code = 'validation_error'
            message = _first_error(response.data) or '请求参数有误。'
        elif isinstance(exc, Throttled):
            code = 'throttled'
            message = _first_error(response.data) or '请求过于频繁。'
        else:
            code = (
                'internal_error'
                if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
                else 'validation_error'
            )
            message = _first_error(response.data) or '请求失败。'
        response.data = {
            'code': code,
            'message': message,
            'errors': _field_errors(response.data),
        }
        return response

    @staticmethod
    def error_response(code, message, status_code, errors=None):
        """Build a canonical activity API error response."""
        serializer = ActivityErrorSerializer({
            'code': code,
            'message': message,
            'errors': errors or {},
        })
        return Response(serializer.data, status=status_code)

    @extend_schema(
        summary="获取活动首页数据",
        description=(
            "获取活动首页所需的数据，包括：\n"
            "- recent_activities: 开始时间在前后一周内的活动（排除取消和审核中的活动），按时间逆序排序\n"
            "- today_activities: 开始时间在今天的活动（不展示已结束的活动），按开始时间由近到远排序\n"
            "- newly_released_activities: 最新一周内发布的活动，按发布时间逆序\n"
            "- prepare_times: 报名截止时间配置列表 [1, 24, 72, 168]（一小时，一天，三天，一周）\n"
            "- signup_activities: 即将截止报名的活动，按截止时间正序，最多返回10条"
        ),
        responses={
            200: OpenApiResponse(
                description="活动首页数据",
                response=ActivityHomepageSerializer,
            ),
            401: OpenApiResponse(description="未登录"),
            403: OpenApiResponse(description="无权限"),
        },
        tags=['活动'],
    )
    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        """Get activity homepage data."""
        nowtime = datetime.now()

        # 开始时间在前后一周内，除了取消和审核中的活动。按时间逆序排序
        recent_activities = Activity.objects.get_recent_activity(
        ).select_related('organization_id')

        # 开始时间在今天的活动,且不展示结束的活动。按开始时间由近到远排序
        activities = Activity.objects.get_today_activity().select_related('organization_id')
        today_activities = [
            {
                "activity": activity,
                "start_time": activity.start.strftime("%H:%M"),
            }
            for activity in activities
        ]

        # 最新一周内发布的活动，按发布的时间逆序
        newly_released_activities = Activity.objects.get_newlyreleased_activity(
        ).select_related('organization_id')

        # 即将截止的活动，按截止时间正序
        prepare_times = Activity.EndBeforeHours.prepare_times

        signup_rec = Activity.objects.activated().select_related(
            'organization_id').filter(
            status=Activity.Status.APPLYING).order_by("category", "apply_end")[:10]
        signup_activities = []
        for activity in signup_rec:
            apply_end = activity.apply_end
            signup_activities.append({
                "activity": activity,
                "apply_end": apply_end,
                "hours_until_deadline": (apply_end - nowtime).total_seconds() // 360 / 10,
            })

        response_data = {
            "recent_activities": recent_activities,
            "today_activities": today_activities,
            "newly_released_activities": newly_released_activities,
            "prepare_times": prepare_times,
            "signup_activities": signup_activities,
        }

        serializer = ActivityHomepageSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="获取活动详情",
        description=(
            "获取指定活动的摘要信息，用于签到页等前端展示。"
        ),
        parameters=[
            OpenApiParameter(
                name='aid',
                type=int,
                location=OpenApiParameter.PATH,
                description='活动 ID',
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="活动详情",
                response=ActivityDetailSerializer,
            ),
            401: OpenApiResponse(
                description="未登录",
                response=ActivityErrorSerializer,
            ),
            404: OpenApiResponse(
                description="活动不存在",
                response=ActivityErrorSerializer,
            ),
        },
        tags=['活动'],
    )
    @action(detail=False, methods=['get'], url_path=r'(?P<aid>\d+)')
    def retrieve_by_id(self, request, aid=None):
        """Get activity summary by ID for check-in page display."""
        try:
            aid = int(aid)
        except (ValueError, TypeError):
            raise ValidationError({"aid": "活动 ID 格式错误"})
        try:
            activity = Activity.objects.select_related('organization_id').get(id=aid)
        except Activity.DoesNotExist:
            raise NotFound("活动不存在")
        serializer = ActivityDetailSerializer(
            activity,
            context={'request': request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        methods=['POST'],
        summary="报名活动",
        description="使用当前个人账号报名指定活动。",
        request=None,
        parameters=[
            OpenApiParameter(
                name='aid',
                type=int,
                location=OpenApiParameter.PATH,
                description='活动 ID',
            ),
        ],
        responses={
            200: ActivityActionResultSerializer,
            401: ActivityErrorSerializer,
            403: ActivityErrorSerializer,
            404: ActivityErrorSerializer,
            409: ActivityErrorSerializer,
        },
        tags=['活动'],
    )
    @extend_schema(
        methods=['DELETE'],
        summary="取消活动报名",
        description="取消当前个人账号对指定活动的报名或申请。",
        request=None,
        parameters=[
            OpenApiParameter(
                name='aid',
                type=int,
                location=OpenApiParameter.PATH,
                description='活动 ID',
            ),
        ],
        responses={
            200: ActivityActionResultSerializer,
            401: ActivityErrorSerializer,
            403: ActivityErrorSerializer,
            404: ActivityErrorSerializer,
            409: ActivityErrorSerializer,
        },
        tags=['活动'],
    )
    @action(
        detail=False,
        methods=['post', 'delete'],
        url_path=r'(?P<aid>\d+)/signup',
    )
    def signup(self, request, aid=None):
        """Sign up for an activity or withdraw the current signup."""
        if not request.user.is_person():
            raise PermissionDenied("请使用个人账号报名活动。")

        try:
            activity_id = int(aid)
        except (ValueError, TypeError):
            raise ValidationError({'aid': '活动 ID 格式错误'})

        with transaction.atomic():
            try:
                user = User.objects.select_for_update().get(
                    pk=request.user.pk,
                )
            except User.DoesNotExist:
                raise AuthenticationFailed("登录状态无效或已过期。")

            if not user.is_person():
                raise PermissionDenied("请使用个人账号报名活动。")
            if request.method == 'POST' and not user.active:
                raise PermissionDenied("当前账号状态不允许报名活动。")

            person = get_person_or_org(user)
            try:
                activity = Activity.objects.select_for_update().get(
                    id=activity_id,
                )
            except Activity.DoesNotExist:
                raise NotFound("活动不存在")

            if request.method == 'POST':
                if not activity.need_apply:
                    return self.error_response(
                        'conflict',
                        '该活动无需报名。',
                        status.HTTP_409_CONFLICT,
                    )
                if activity.status != Activity.Status.APPLYING:
                    return self.error_response(
                        'conflict',
                        '活动报名暂未开放或已经截止。',
                        status.HTTP_409_CONFLICT,
                    )
                if (
                    activity.inner
                    and not Position.objects.activated().filter(
                        person=person,
                        org=activity.organization_id,
                    ).exists()
                ):
                    return self.error_response(
                        'permission_denied',
                        f'该活动仅面向{activity.organization_id}内部成员。',
                        status.HTTP_403_FORBIDDEN,
                    )
                try:
                    participation = apply_activity_for_person(
                        person,
                        activity,
                    )
                except ActivityException as exc:
                    return self.error_response(
                        'conflict',
                        str(exc),
                        status.HTTP_409_CONFLICT,
                    )
                message = (
                    '活动申请已提交，请等待报名结果。'
                    if activity.bidding
                    else '报名成功。'
                )
            else:
                if activity.status not in [
                    Activity.Status.APPLYING,
                    Activity.Status.WAITING,
                ]:
                    return self.error_response(
                        'conflict',
                        '当前状态不允许取消报名。',
                        status.HTTP_409_CONFLICT,
                    )
                try:
                    participation = withdraw_activity_for_person(
                        person,
                        activity,
                    )
                except ActivityException as exc:
                    return self.error_response(
                        'conflict',
                        str(exc),
                        status.HTTP_409_CONFLICT,
                    )
                message = (
                    '已取消申请。' if activity.bidding else '已取消报名。'
                )

        serializer = ActivityActionResultSerializer({
            'message': message,
            'participation_status': participation.status,
            'current_participants': activity.current_participants,
        })
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="活动签到",
        description=(
            "对指定活动进行签到。需要个人账号，且已报名该活动。"
        ),
        request=ActivityCheckinRequestSerializer,
        responses={
            200: OpenApiResponse(
                description="签到成功",
                response=ActivityMessageSerializer,
            ),
            400: OpenApiResponse(
                description="请求参数错误或业务校验失败",
                response=ActivityErrorSerializer,
            ),
            401: OpenApiResponse(
                description="未登录",
                response=ActivityErrorSerializer,
            ),
            403: OpenApiResponse(
                description="需使用个人账号",
                response=ActivityErrorSerializer,
            ),
        },
        tags=['活动'],
    )
    @action(detail=False, methods=['post'], url_path='checkin')
    def checkin(self, request):
        """Submit activity check-in."""
        if not request.user.is_person():
            raise PermissionDenied("请使用个人账号签到")

        data = request.data.copy()
        if 'aid' not in data and request.query_params.get('aid') is not None:
            data['aid'] = request.query_params['aid']
        request_serializer = ActivityCheckinRequestSerializer(data=data)
        request_serializer.is_valid(raise_exception=True)
        aid = request_serializer.validated_data['aid']

        person = get_person_or_org(request.user)
        success, message = do_checkin(person, aid)
        if not success:
            raise ValidationError(message)

        return Response({"message": message}, status=status.HTTP_200_OK)
