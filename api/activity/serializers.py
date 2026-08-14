"""
Serializers for activity API.
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from app.models import Activity, Participation
from app.utils import get_person_or_org


class ActivitySummarySerializer(serializers.ModelSerializer):
    """Serializer for activity summary display."""

    organization_id = serializers.IntegerField(
        source='organization_id.id',
        read_only=True,
        help_text="Organization ID"
    )
    organization_name = serializers.CharField(
        source='organization_id.oname',
        read_only=True,
        help_text="Organization name"
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
        help_text="Activity status display text"
    )
    category_display = serializers.CharField(
        source='get_category_display',
        read_only=True,
        help_text="Activity category display text"
    )
    has_tag = serializers.SerializerMethodField(
        help_text="Whether activity should display tags"
    )
    popular_level = serializers.SerializerMethodField(
        help_text="Popularity level (0: normal, 1: popular, 2: full)"
    )
    url = serializers.URLField(
        source='URL',
        read_only=True,
        help_text="Activity related URL"
    )

    class Meta:
        model = Activity
        fields = [
            'id',
            'title',
            'organization_id',
            'organization_name',
            'start',
            'end',
            'location',
            'introduction',
            'status',
            'status_display',
            'need_apply',
            'apply_end',
            'bidding',
            'need_checkin',
            'inner',
            'capacity',
            'current_participants',
            'url',
            'category',
            'category_display',
            'has_tag',
            'popular_level',
        ]
        read_only_fields = fields

    def get_has_tag(self, obj: Activity) -> bool:
        """Get whether activity should display tags."""
        return obj.has_tag()

    def get_popular_level(self, obj: Activity) -> int:
        """Get popularity level of the activity."""
        return obj.popular_level()


class ActivityDetailSerializer(ActivitySummarySerializer):
    """Activity detail including the selected person's signup status."""

    participation_status = serializers.SerializerMethodField(
        help_text="Current person's signup/check-in status, or null",
    )

    class Meta(ActivitySummarySerializer.Meta):
        fields = ActivitySummarySerializer.Meta.fields + [
            'participation_status',
        ]
        read_only_fields = fields

    @extend_schema_field(
        serializers.ChoiceField(
            choices=Participation.AttendStatus.choices,
            allow_null=True,
        ),
    )
    def get_participation_status(self, obj: Activity) -> str | None:
        """Return the participation status for the authenticated person."""
        request = self.context.get('request')
        if request is None or not request.user.is_person():
            return None
        person = get_person_or_org(request.user)
        return Participation.objects.filter(
            activity=obj,
            person=person,
        ).values_list('status', flat=True).first()


class ActivityActionResultSerializer(serializers.Serializer):
    """Response after signing up for or withdrawing from an activity."""

    message = serializers.CharField(help_text="User-facing result message")
    participation_status = serializers.ChoiceField(
        choices=Participation.AttendStatus.choices,
        help_text="Updated signup/check-in status",
    )
    current_participants = serializers.IntegerField(
        min_value=0,
        help_text="Updated number of registered participants",
    )


class ActivityCheckinRequestSerializer(serializers.Serializer):
    """Request body for checking in to an activity."""

    aid = serializers.IntegerField(
        min_value=1,
        help_text="Activity ID",
    )


class ActivityMessageSerializer(serializers.Serializer):
    """Simple successful activity operation response."""

    message = serializers.CharField(help_text="User-facing result message")


class ActivityErrorSerializer(serializers.Serializer):
    """Canonical error response for activity mini-program endpoints."""

    code = serializers.CharField(help_text="Stable machine-readable error code")
    message = serializers.CharField(help_text="Concise user-facing message")
    errors = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Field errors; empty when the error is not field-specific",
    )


class TodayActivitySerializer(serializers.Serializer):
    """Serializer for today's activity item."""

    activity = ActivitySummarySerializer(
        help_text="Activity information"
    )
    start_time = serializers.CharField(
        help_text="Activity start time in HH:MM format"
    )


class SignupActivitySerializer(serializers.Serializer):
    """Serializer for signup deadline activity item."""

    activity = ActivitySummarySerializer(
        help_text="Activity information"
    )
    apply_end = serializers.DateTimeField(
        help_text="Application deadline"
    )
    hours_until_deadline = serializers.FloatField(
        help_text="Hours until signup deadline (rounded to 0.1h)"
    )


class ActivityHomepageSerializer(serializers.Serializer):
    """Serializer for activity homepage data."""

    recent_activities = ActivitySummarySerializer(
        many=True,
        help_text="Activities starting within one week before and after today"
    )
    today_activities = TodayActivitySerializer(
        many=True,
        help_text="Activities starting today"
    )
    newly_released_activities = ActivitySummarySerializer(
        many=True,
        help_text="Activities published within the last week"
    )
    prepare_times = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Prepare times in hours: [1, 24, 72, 168]"
    )
    signup_activities = SignupActivitySerializer(
        many=True,
        help_text="Activities with upcoming signup deadlines (top 10)"
    )
