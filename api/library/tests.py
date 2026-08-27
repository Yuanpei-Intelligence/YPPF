"""
Tests for library API.
"""
from unittest import mock

from django.test import SimpleTestCase
from django.urls import resolve
from rest_framework import status as http_status
from rest_framework.test import APIClient, APITestCase

from generic.models import User

from api.library.views import LibraryViewSet
from api.library.serializers import (
    BookSerializer,
    LibraryWelcomeSerializer,
    BookSearchQuerySerializer,
    LibraryConfigSerializer,
    LibraryActivitiesQuerySerializer,
    LibraryRecommendationsQuerySerializer,
    LibraryRecordsQuerySerializer,
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

    def test_library_query_serializer_fields(self):
        """Endpoint-specific query serializers expose their public fields."""
        self.assertEqual(
            set(LibraryRecordsQuerySerializer().fields),
            {"returned"},
        )
        self.assertEqual(
            set(LibraryActivitiesQuerySerializer().fields),
            {"num"},
        )
        self.assertEqual(
            set(LibraryRecommendationsQuerySerializer().fields),
            {"num", "newest"},
        )


class LibraryAPITestCase(APITestCase):
    """Exercise the standardized library API error contract."""

    def setUp(self):
        self.client = APIClient()
        self.person = User.objects.create_user(
            username="S000001",
            password="testpass123",
            name="Library Person",
            usertype=User.Type.STUDENT,
        )
        self.organization = User.objects.create_user(
            username="ORG001",
            password="testpass123",
            name="Library Organization",
            usertype=User.Type.ORG,
        )

    def assert_error(self, response, expected_status, expected_code):
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(set(response.data), {"code", "message", "errors"})
        self.assertEqual(response.data["code"], expected_code)
        self.assertIsInstance(response.data["message"], str)
        self.assertIsInstance(response.data["errors"], dict)

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.person)

    def test_config_requires_authentication(self):
        response = self.client.get("/api/v2/library/config/")

        self.assert_error(
            response,
            http_status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
        )
        self.assertEqual(response.data["errors"], {})

    def test_search_rejects_invalid_returned_filter(self):
        self.authenticate()

        response = self.client.get(
            "/api/v2/library/search/",
            {"returned": "maybe"},
        )

        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "validation_error",
        )
        self.assertEqual(
            response.data["errors"]["returned"][0]["code"],
            "invalid",
        )

    def test_records_rejects_invalid_returned_filter(self):
        self.authenticate()

        response = self.client.get(
            "/api/v2/library/records/",
            {"returned": "maybe"},
        )

        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "validation_error",
        )
        self.assertEqual(
            response.data["errors"]["returned"][0]["code"],
            "invalid_choice",
        )

    def test_records_reports_missing_reader_account(self):
        self.authenticate()

        response = self.client.get("/api/v2/library/records/")

        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "library.reader_account_missing",
        )
        self.assertEqual(response.data["errors"], {})

    def test_records_rejects_organization_account(self):
        self.authenticate(self.organization)

        response = self.client.get("/api/v2/library/records/")

        self.assert_error(
            response,
            http_status.HTTP_403_FORBIDDEN,
            "permission_denied",
        )
        self.assertEqual(response.data["errors"], {})

    def test_activities_rejects_out_of_range_num(self):
        self.authenticate()

        response = self.client.get(
            "/api/v2/library/activities/",
            {"num": 0},
        )

        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "validation_error",
        )
        self.assertEqual(
            response.data["errors"]["num"][0]["code"],
            "min_value",
        )

    def test_recommendations_rejects_invalid_query(self):
        self.authenticate()

        response = self.client.get(
            "/api/v2/library/recommendations/",
            {"num": 51, "newest": "maybe"},
        )

        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "validation_error",
        )
        self.assertEqual(
            response.data["errors"]["num"][0]["code"],
            "max_value",
        )
        self.assertEqual(
            response.data["errors"]["newest"][0]["code"],
            "invalid",
        )

    @mock.patch("api.library.views.unlock_achievement")
    @mock.patch("api.library.views.search_books", return_value=[])
    def test_search_passes_validated_query_values(
        self,
        search_books_mock,
        unlock_achievement_mock,
    ):
        self.authenticate()

        response = self.client.get(
            "/api/v2/library/search/",
            {"keywords": "history", "returned": "true"},
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        search_books_mock.assert_called_once_with(
            keywords="history",
            returned=True,
        )
        unlock_achievement_mock.assert_called_once_with(
            self.person,
            "使用一次元培书房查询",
        )


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
