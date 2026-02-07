"""
REST APIs for activity homepage data.
"""
from __future__ import annotations

from datetime import datetime

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from drf_spectacular.utils import extend_schema, OpenApiResponse

from api.authentication import WxJWTAuthentication
from api.activity.serializers import ActivityHomepageSerializer, ActivitySummarySerializer
from app.models import Activity
from app.utils import get_person_or_org
from api.activity.checkin import do_checkin


class ActivityViewSet(viewsets.ViewSet):
    """
    ViewSet for activity homepage data.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

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
        description="获取指定活动的摘要信息，用于签到页等前端展示。",
        responses={
            200: OpenApiResponse(
                description="活动详情",
                response=ActivitySummarySerializer,
            ),
            404: OpenApiResponse(description="活动不存在"),
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
        serializer = ActivitySummarySerializer(activity)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="活动签到",
        description="对指定活动进行签到。需要个人账号，且已报名该活动。",
        request={
            "application/json": {
                "type": "object",
                "required": ["aid"],
                "properties": {
                    "aid": {"type": "integer", "description": "活动 ID"},
                },
            },
            "application/x-www-form-urlencoded": {
                "type": "object",
                "required": ["aid"],
                "properties": {
                    "aid": {"type": "integer", "description": "活动 ID"},
                },
            },
        },
        responses={
            200: OpenApiResponse(
                description="签到成功",
                response={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "提示信息"},
                    },
                },
            ),
            400: OpenApiResponse(description="请求参数错误或业务校验失败"),
            403: OpenApiResponse(description="需使用个人账号"),
        },
        tags=['活动'],
    )
    @action(detail=False, methods=['post'], url_path='checkin')
    def checkin(self, request):
        """Submit activity check-in."""
        if not request.user.is_person():
            raise PermissionDenied("请使用个人账号签到")

        aid = request.data.get("aid") or request.query_params.get("aid")
        if aid is None:
            raise ValidationError({"aid": "缺少活动 ID"})
        try:
            aid = int(aid)
        except (ValueError, TypeError):
            raise ValidationError({"aid": "活动 ID 格式错误"})

        person = get_person_or_org(request.user)
        success, message = do_checkin(person, aid)
        if not success:
            raise ValidationError(message)

        return Response({"message": message}, status=status.HTTP_200_OK)
