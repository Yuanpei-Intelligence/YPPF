"""
REST APIs for notification management.
"""
from __future__ import annotations

from datetime import datetime

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from app.models import Notification
from app.notification_utils import notification_status_change
from api.authentication import WxJWTAuthentication
from api.exceptions import (
    APIError,
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)
from api.notification.serializers import (
    NotificationBulkOperationSerializer,
    NotificationSerializer,
    NotificationStatusUpdateSerializer,
    NotificationListQuerySerializer,
    NotificationStatisticsSerializer,
)
from utils.global_messages import SUCCEED


def error_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
    )


class NotificationViewSet(StandardizedExceptionHandlerMixin, viewsets.ViewSet):
    """
    ViewSet for managing user notifications.

    Provides endpoints for:
    - Listing notifications (filtered by status, type, etc.)
    - Retrieving a specific notification
    - Updating notification status (mark as read/unread/delete)
    - Bulk operations (mark all as read, delete all)
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        """Get notifications for the current user."""
        return Notification.objects.activated().filter(
            receiver=self.request.user
        ).select_related("sender")

    def _get_notification(self, pk):
        try:
            return self.get_queryset().get(pk=pk)
        except (Notification.DoesNotExist, TypeError, ValueError):
            raise NotFound("通知不存在。")

    @staticmethod
    def _change_status(notification, to_status=None):
        context = notification_status_change(notification, to_status)
        if context.get("warn_code") != SUCCEED:
            raise APIError(
                code="notification.state_conflict",
                message="通知状态已发生变化，请刷新后重试。",
                status_code=status.HTTP_409_CONFLICT,
            )

    @staticmethod
    def _bulk_update(queryset, **updates):
        with transaction.atomic():
            notification_ids = list(
                queryset.select_for_update()
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            if not notification_ids:
                return 0
            return Notification.objects.filter(
                pk__in=notification_ids
            ).update(**updates)

    @extend_schema(
        description="List all notifications for the authenticated user",
        parameters=[
            OpenApiParameter(
                name='status',
                description='Filter by notification status',
                required=False,
                type=OpenApiTypes.INT,
                enum=[0, 1, 2],
            ),
            OpenApiParameter(
                name='typename',
                description='Filter by notification type',
                required=False,
                type=OpenApiTypes.INT,
                enum=[0, 1],
            ),
            OpenApiParameter(
                name='ordering',
                description='Order by field (default: -start_time)',
                required=False,
                type=OpenApiTypes.STR,
                enum=['start_time', '-start_time',
                      'finish_time', '-finish_time'],
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=NotificationSerializer(many=True),
                description="List of notifications"
            ),
            400: error_response("Invalid filter or ordering parameter"),
            401: error_response("Authentication required or token invalid"),
        },
        tags=['通知']
    )
    def list(self, request):
        """List notifications with optional filtering and ordering."""
        queryset = self.get_queryset()

        query_serializer = NotificationListQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data
        if "status" in params:
            queryset = queryset.filter(status=params["status"])
        if "typename" in params:
            queryset = queryset.filter(typename=params["typename"])
        queryset = queryset.order_by(params["ordering"])

        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        description="Retrieve a specific notification by ID",
        responses={
            200: NotificationSerializer,
            401: error_response("Authentication required or token invalid"),
            404: error_response("Notification not found or not visible"),
        },
        tags=['通知']
    )
    def retrieve(self, request, pk=None):
        """Get a specific notification."""
        notification = self._get_notification(pk)

        serializer = NotificationSerializer(notification)
        return Response(serializer.data)

    @extend_schema(
        description="Update notification status",
        request=NotificationStatusUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=NotificationSerializer,
                description="Notification updated successfully"
            ),
            400: error_response("Invalid status"),
            401: error_response("Authentication required or token invalid"),
            404: error_response("Notification not found or not visible"),
            409: error_response("Notification state changed concurrently"),
        },
        tags=['通知']
    )
    @action(detail=True, methods=['patch'], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update the status of a notification."""
        notification = self._get_notification(pk)

        serializer = NotificationStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        to_status = serializer.validated_data["status"]
        self._change_status(notification, to_status)

        # Refresh the notification from database
        notification.refresh_from_db()
        response_serializer = NotificationSerializer(notification)
        return Response(response_serializer.data)

    @extend_schema(
        description="Toggle notification status (read <-> unread)",
        responses={
            200: OpenApiResponse(
                response=NotificationSerializer,
                description="Notification toggled successfully"
            ),
            401: error_response("Authentication required or token invalid"),
            404: error_response("Notification not found or not visible"),
            409: error_response("Notification state changed concurrently"),
        },
        tags=['通知']
    )
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """Toggle notification status between read and unread."""
        notification = self._get_notification(pk)
        self._change_status(notification)

        # Refresh the notification from database
        notification.refresh_from_db()
        response_serializer = NotificationSerializer(notification)
        return Response(response_serializer.data)

    @extend_schema(
        description="Mark all unread notifications as read",
        responses={
            200: OpenApiResponse(
                response=NotificationBulkOperationSerializer,
                description="All notifications marked as read",
            ),
            401: error_response("Authentication required or token invalid"),
        },
        tags=['通知']
    )
    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        """Mark all unread notifications as read."""
        notifications = Notification.objects.activated().filter(
            receiver=request.user,
            typename=Notification.Type.NEEDREAD,
            status=Notification.Status.UNDONE
        )
        count = self._bulk_update(
            notifications,
            status=Notification.Status.DONE,
            finish_time=datetime.now(),
        )

        return Response({
            "message": f"已将 {count} 条通知标记为已读。",
            "count": count,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        description="Delete all read notifications",
        responses={
            200: OpenApiResponse(
                response=NotificationBulkOperationSerializer,
                description="All read notifications deleted",
            ),
            401: error_response("Authentication required or token invalid"),
        },
        tags=['通知']
    )
    @action(detail=False, methods=['post'], url_path='delete-all-read')
    def delete_all_read(self, request):
        """Delete all read notifications."""
        notifications = Notification.objects.activated().filter(
            receiver=request.user,
            typename=Notification.Type.NEEDREAD,
            status=Notification.Status.DONE
        )
        count = self._bulk_update(
            notifications,
            status=Notification.Status.DELETE,
        )

        return Response({
            "message": f"已删除 {count} 条已读通知。",
            "count": count,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        description="Get notification statistics for the current user",
        responses={
            200: NotificationStatisticsSerializer,
            401: error_response("Authentication required or token invalid"),
        },
        tags=['通知']
    )
    @action(detail=False, methods=['get'], url_path='statistics')
    def statistics(self, request):
        """Get notification statistics (counts by status and type)."""
        queryset = self.get_queryset()

        stats = {
            'total': queryset.count(),
            'unread': queryset.filter(status=Notification.Status.UNDONE).count(),
            'read': queryset.filter(status=Notification.Status.DONE).count(),
            'need_read': queryset.filter(typename=Notification.Type.NEEDREAD).count(),
            'need_do': queryset.filter(typename=Notification.Type.NEEDDO).count(),
        }

        serializer = NotificationStatisticsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)
