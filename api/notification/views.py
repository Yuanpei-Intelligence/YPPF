"""
REST APIs for notification management.
"""
from __future__ import annotations

from datetime import datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db import transaction

from app.models import Notification
from app.notification_utils import notification_status_change
from api.notification.serializers import (
    NotificationSerializer,
    NotificationStatusUpdateSerializer,
    NotificationListQuerySerializer,
    NotificationStatisticsSerializer,
)
from api.authentication import WxJWTAuthentication


class NotificationViewSet(viewsets.ViewSet):
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
        ).select_related('sender')

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
        },
        tags=['通知']
    )
    def list(self, request):
        """List notifications with optional filtering and ordering."""
        queryset = self.get_queryset()

        # Apply filters
        status_param = request.query_params.get('status')
        if status_param is not None:
            queryset = queryset.filter(status=status_param)

        typename_param = request.query_params.get('typename')
        if typename_param is not None:
            queryset = queryset.filter(typename=typename_param)

        # Apply ordering
        ordering = request.query_params.get('ordering', '-start_time')
        queryset = queryset.order_by(ordering)

        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        description="Retrieve a specific notification by ID",
        responses={
            200: NotificationSerializer,
            404: OpenApiResponse(description="Notification not found"),
            403: OpenApiResponse(description="Permission denied"),
        },
        tags=['通知']
    )
    def retrieve(self, request, pk=None):
        """Get a specific notification."""
        try:
            notification = Notification.objects.get(
                id=pk, receiver=request.user)
        except Notification.DoesNotExist:
            raise NotFound("Notification not found")

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
            400: OpenApiResponse(description="Invalid status"),
            404: OpenApiResponse(description="Notification not found"),
            403: OpenApiResponse(description="Permission denied"),
        },
        tags=['通知']
    )
    @action(detail=True, methods=['patch'], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update the status of a notification."""
        try:
            notification = Notification.objects.get(
                id=pk, receiver=request.user)
        except Notification.DoesNotExist:
            raise NotFound("Notification not found")

        serializer = NotificationStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        to_status = serializer.validated_data['status']

        with transaction.atomic():
            context = notification_status_change(notification, to_status)

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
            404: OpenApiResponse(description="Notification not found"),
            403: OpenApiResponse(description="Permission denied"),
        },
        tags=['通知']
    )
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """Toggle notification status between read and unread."""
        try:
            notification = Notification.objects.get(
                id=pk, receiver=request.user)
        except Notification.DoesNotExist:
            raise NotFound("Notification not found")

        with transaction.atomic():
            context = notification_status_change(notification)

        # Refresh the notification from database
        notification.refresh_from_db()
        response_serializer = NotificationSerializer(notification)
        return Response(response_serializer.data)

    @extend_schema(
        description="Mark all unread notifications as read",
        responses={
            200: OpenApiResponse(description="All notifications marked as read"),
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
        count = notifications.count()

        with transaction.atomic():
            notifications.update(
                status=Notification.Status.DONE,
                finish_time=datetime.now()
            )

        return Response({
            "message": f"Successfully marked {count} notifications as read",
            "count": count
        }, status=status.HTTP_200_OK)

    @extend_schema(
        description="Delete all read notifications",
        responses={
            200: OpenApiResponse(description="All read notifications deleted"),
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
        count = notifications.count()

        with transaction.atomic():
            notifications.update(status=Notification.Status.DELETE)

        return Response({
            "message": f"Successfully deleted {count} notifications",
            "count": count
        }, status=status.HTTP_200_OK)

    @extend_schema(
        description="Get notification statistics for the current user",
        responses={
            200: NotificationStatisticsSerializer,
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
