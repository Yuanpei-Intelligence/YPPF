"""
Tests for library API.
Basic tests that don't require database connection.
"""
from django.test import SimpleTestCase
from django.urls import reverse, resolve

from api.library.views import LibraryViewSet
from api.library.serializers import (
    BookSerializer,
    LibraryWelcomeSerializer,
    BookSearchQuerySerializer,
    LibraryConfigSerializer,
)


class LibraryURLTestCase(SimpleTestCase):
    """Test URL routing for library API."""

    def test_welcome_url_resolves(self):
        """Test welcome URL resolves correctly."""
        url = '/api/v2/library/welcome/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, LibraryViewSet)
        self.assertEqual(resolver.func.actions['get'], 'welcome')

    def test_search_url_resolves(self):
        """Test search URL resolves correctly."""
        url = '/api/v2/library/search/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, LibraryViewSet)
        self.assertEqual(resolver.func.actions['get'], 'search')

    def test_records_url_resolves(self):
        """Test records URL resolves correctly."""
        url = '/api/v2/library/records/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, LibraryViewSet)
        self.assertEqual(resolver.func.actions['get'], 'records')

    def test_activities_url_resolves(self):
        """Test activities URL resolves correctly."""
        url = '/api/v2/library/activities/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, LibraryViewSet)
        self.assertEqual(resolver.func.actions['get'], 'activities')

    def test_recommendations_url_resolves(self):
        """Test recommendations URL resolves correctly."""
        url = '/api/v2/library/recommendations/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, LibraryViewSet)
        self.assertEqual(resolver.func.actions['get'], 'recommendations')

    def test_config_url_resolves(self):
        """Test config URL resolves correctly."""
        url = '/api/v2/library/config/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, LibraryViewSet)
        self.assertEqual(resolver.func.actions['get'], 'config')


class SerializerFieldsTestCase(SimpleTestCase):
    """Test serializer field definitions."""

    def test_book_serializer_fields(self):
        """Test BookSerializer has required fields."""
        serializer = BookSerializer()
        expected_fields = ['id', 'identity_code',
                           'title', 'author', 'publisher', 'returned']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_book_search_query_serializer_fields(self):
        """Test BookSearchQuerySerializer has required fields."""
        serializer = BookSearchQuerySerializer()
        expected_fields = ['keywords', 'identity_code',
                           'title', 'author', 'publisher', 'returned']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_library_config_serializer_fields(self):
        """Test LibraryConfigSerializer has required fields."""
        serializer = LibraryConfigSerializer()
        expected_fields = ['opening_time_start',
                           'opening_time_end', 'organization_name']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_library_welcome_serializer_fields(self):
        """Test LibraryWelcomeSerializer has required fields."""
        serializer = LibraryWelcomeSerializer()
        expected_fields = ['activities', 'opening_time_start', 'opening_time_end',
                           'records_list', 'recommendation']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))


class ViewSetConfigTestCase(SimpleTestCase):
    """Test ViewSet configuration."""

    def test_viewset_has_permission_classes(self):
        """Test LibraryViewSet has permission classes."""
        from rest_framework.permissions import IsAuthenticated
        self.assertIn(IsAuthenticated, LibraryViewSet.permission_classes)

    def test_viewset_has_authentication_classes(self):
        """Test LibraryViewSet has authentication classes."""
        from api.authentication import WxJWTAuthentication
        self.assertIn(WxJWTAuthentication,
                      LibraryViewSet.authentication_classes)

    def test_viewset_has_welcome_action(self):
        """Test LibraryViewSet has welcome action."""
        self.assertTrue(hasattr(LibraryViewSet, 'welcome'))
        self.assertTrue(callable(getattr(LibraryViewSet, 'welcome')))

    def test_viewset_has_search_action(self):
        """Test LibraryViewSet has search action."""
        self.assertTrue(hasattr(LibraryViewSet, 'search'))
        self.assertTrue(callable(getattr(LibraryViewSet, 'search')))

    def test_viewset_has_records_action(self):
        """Test LibraryViewSet has records action."""
        self.assertTrue(hasattr(LibraryViewSet, 'records'))
        self.assertTrue(callable(getattr(LibraryViewSet, 'records')))

    def test_viewset_has_activities_action(self):
        """Test LibraryViewSet has activities action."""
        self.assertTrue(hasattr(LibraryViewSet, 'activities'))
        self.assertTrue(callable(getattr(LibraryViewSet, 'activities')))

    def test_viewset_has_recommendations_action(self):
        """Test LibraryViewSet has recommendations action."""
        self.assertTrue(hasattr(LibraryViewSet, 'recommendations'))
        self.assertTrue(callable(getattr(LibraryViewSet, 'recommendations')))

    def test_viewset_has_config_action(self):
        """Test LibraryViewSet has config action."""
        self.assertTrue(hasattr(LibraryViewSet, 'config'))
        self.assertTrue(callable(getattr(LibraryViewSet, 'config')))
