"""
Serializers for notification API.
"""
from rest_framework import serializers
from app.models import Notification
from generic.models import User


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for notification with all fields."""
    
    sender_name = serializers.CharField(
        source='sender.name', 
        read_only=True,
        help_text="Sender's name"
    )
    status_display = serializers.CharField(
        source='get_status_display', 
        read_only=True,
        help_text="Status display text"
    )
    typename_display = serializers.CharField(
        source='get_typename_display', 
        read_only=True,
        help_text="Type display text"
    )
    title_display = serializers.CharField(
        source='get_title_display', 
        read_only=True,
        help_text="Title display text"
    )
    
    class Meta:
        model = Notification
        fields = [
            'id',
            'sender',
            'sender_name',
            'status',
            'status_display',
            'title',
            'title_display',
            'content',
            'start_time',
            'finish_time',
            'typename',
            'typename_display',
            'URL',
            'anonymous_flag',
        ]
        read_only_fields = [
            'id',
            'sender',
            'sender_name',
            'start_time',
            'finish_time',
            'status_display',
            'typename_display',
            'title_display',
        ]


class NotificationStatusUpdateSerializer(serializers.Serializer):
    """Serializer for updating notification status."""
    
    status = serializers.ChoiceField(
        choices=Notification.Status.choices,
        help_text="New status for the notification"
    )


class NotificationListQuerySerializer(serializers.Serializer):
    """Serializer for query parameters in list endpoint."""
    
    status = serializers.ChoiceField(
        choices=Notification.Status.choices,
        required=False,
        help_text="Filter by notification status"
    )
    typename = serializers.ChoiceField(
        choices=Notification.Type.choices,
        required=False,
        help_text="Filter by notification type"
    )
    ordering = serializers.ChoiceField(
        choices=['start_time', '-start_time', 'finish_time', '-finish_time'],
        default='-start_time',
        required=False,
        help_text="Order by field"
    )


class NotificationStatisticsSerializer(serializers.Serializer):
    """Serializer for notification statistics."""
    
    total = serializers.IntegerField(
        help_text="Total number of notifications"
    )
    unread = serializers.IntegerField(
        help_text="Number of unread notifications"
    )
    read = serializers.IntegerField(
        help_text="Number of read notifications"
    )
    need_read = serializers.IntegerField(
        help_text="Number of need_read type notifications"
    )
    need_do = serializers.IntegerField(
        help_text="Number of need_do type notifications"
    )
