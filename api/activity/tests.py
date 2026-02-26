"""
Tests for activity API.
"""
from django.test import SimpleTestCase
from django.urls import resolve

from api.activity.views import ActivityViewSet
from api.activity.serializers import (
    ActivitySummarySerializer,
    ActivityHomepageSerializer,
    TodayActivitySerializer,
    SignupActivitySerializer,
)


class ActivityURLTestCase(SimpleTestCase):
    """Test URL routing for activity API."""

    def test_overview_url_resolves(self):
        """Test overview URL resolves correctly."""
        url = '/api/v2/activity/overview/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, ActivityViewSet)
        self.assertEqual(resolver.func.actions['get'], 'overview')


class SerializerFieldsTestCase(SimpleTestCase):
    """Test serializer field definitions."""

    def test_activity_summary_serializer_fields(self):
        """Test ActivitySummarySerializer has required fields."""
        serializer = ActivitySummarySerializer()
        expected_fields = [
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
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_today_activity_serializer_fields(self):
        """Test TodayActivitySerializer has required fields."""
        serializer = TodayActivitySerializer()
        expected_fields = ['activity', 'start_time']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_signup_activity_serializer_fields(self):
        """Test SignupActivitySerializer has required fields."""
        serializer = SignupActivitySerializer()
        expected_fields = ['activity', 'apply_end', 'hours_until_deadline']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_activity_homepage_serializer_fields(self):
        """Test ActivityHomepageSerializer has required fields."""
        serializer = ActivityHomepageSerializer()
        expected_fields = [
            'recent_activities',
            'today_activities',
            'newly_released_activities',
            'prepare_times',
            'signup_activities',
        ]
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))


class ViewSetConfigTestCase(SimpleTestCase):
    """Test ViewSet configuration."""

    def test_viewset_has_permission_classes(self):
        """Test ActivityViewSet has permission classes."""
        from rest_framework.permissions import IsAuthenticated
        self.assertIn(IsAuthenticated, ActivityViewSet.permission_classes)

    def test_viewset_has_authentication_classes(self):
        """Test ActivityViewSet has authentication classes."""
        from api.authentication import WxJWTAuthentication
        self.assertIn(WxJWTAuthentication,
                      ActivityViewSet.authentication_classes)

    def test_viewset_has_overview_action(self):
        """Test ActivityViewSet has overview action."""
        self.assertTrue(hasattr(ActivityViewSet, 'overview'))
        self.assertTrue(callable(getattr(ActivityViewSet, 'overview')))
