"""
Serializers for group (organization) subscription API.
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from app.models import Organization, OrganizationType


class OrganizationTypeSerializer(serializers.ModelSerializer):
    """Serializer for organization type."""
    
    class Meta:
        model = OrganizationType
        fields = [
            'otype_id',
            'otype_name',
            'allow_unsubscribe',
        ]


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for organization."""
    
    username = serializers.CharField(
        source='organization_id.username',
        read_only=True,
        help_text="Organization username (e.g., zz00123)"
    )
    otype_name = serializers.CharField(
        source='otype.otype_name',
        read_only=True,
        help_text="Organization type name"
    )
    otype_id = serializers.IntegerField(
        source='otype.otype_id',
        read_only=True,
        help_text="Organization type ID"
    )
    avatar_url = serializers.SerializerMethodField(
        help_text="Avatar URL"
    )
    
    class Meta:
        model = Organization
        fields = [
            'id',
            'username',
            'oname',
            'otype_id',
            'otype_name',
            'introduction',
            'avatar_url',
        ]
    
    @extend_schema_field(OpenApiTypes.URI)
    def get_avatar_url(self, obj):
        return obj.get_user_ava()


class OrganizationWithSubscribeSerializer(OrganizationSerializer):
    """Serializer for organization with subscription status."""
    
    subscribed = serializers.SerializerMethodField(
        help_text="Whether the current user is subscribed"
    )
    
    class Meta(OrganizationSerializer.Meta):
        fields = OrganizationSerializer.Meta.fields + ['subscribed']
    
    @extend_schema_field(serializers.BooleanField())
    def get_subscribed(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_person():
            return False
        unsubscribe_set = self.context.get('unsubscribe_set', set())
        username = obj.organization_id.username
        return username not in unsubscribe_set


class OrganizationTypeWithOrgsSerializer(serializers.Serializer):
    """Serializer for organization type with its organizations."""
    
    otype_id = serializers.IntegerField()
    otype_name = serializers.CharField()
    allow_unsubscribe = serializers.BooleanField()
    organizations = OrganizationWithSubscribeSerializer(many=True)


class SubscriptionListResponseSerializer(serializers.Serializer):
    """Serializer for subscription list response."""
    
    is_person = serializers.BooleanField(
        help_text="Whether the current user is a person (not organization)"
    )
    readonly = serializers.BooleanField(
        help_text="Whether subscription is readonly (for organization accounts)"
    )
    organization_types = OrganizationTypeWithOrgsSerializer(many=True)


class SubscribeStatusUpdateSerializer(serializers.Serializer):
    """Serializer for updating subscription status."""
    
    id = serializers.CharField(
        required=False,
        help_text="Organization username to subscribe/unsubscribe"
    )
    otype = serializers.IntegerField(
        required=False,
        help_text="Organization type ID for batch subscribe/unsubscribe"
    )
    status = serializers.BooleanField(
        help_text="True to subscribe, False to unsubscribe"
    )
    
    def validate(self, data):
        if 'id' not in data and 'otype' not in data:
            raise serializers.ValidationError(
                "Either 'id' (organization username) or 'otype' (type ID) is required"
            )
        if 'id' in data and 'otype' in data:
            raise serializers.ValidationError(
                "Cannot specify both 'id' and 'otype'"
            )
        return data
