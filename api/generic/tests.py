"""Tests for generic mini-program APIs."""

from unittest import mock

from rest_framework import status as http_status
from rest_framework.test import APIClient, APITestCase


class CarouselAPITestCase(APITestCase):
    """Test the public carousel success and error contracts."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/v2/generic/carousel/"

    def assert_error(self, response, expected_status, expected_code):
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(set(response.data), {"code", "message", "errors"})
        self.assertEqual(response.data["code"], expected_code)
        self.assertIsInstance(response.data["message"], str)
        self.assertIsInstance(response.data["errors"], dict)

    def test_carousel_is_public_and_preserves_success_shape(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(set(response.data), {"items"})
        self.assertEqual(
            response.data["items"],
            [{
                "image": "/static/assets/img/homepage_fallback.jpeg",
                "redirect_url": "/",
            }],
        )

    def test_method_not_allowed_uses_standard_error_shape(self):
        response = self.client.post(self.url, {}, format="json")

        self.assert_error(
            response,
            http_status.HTTP_405_METHOD_NOT_ALLOWED,
            "method_not_allowed",
        )
        self.assertEqual(response.data["errors"], {})

    @mock.patch(
        "api.generic.views.CarouselView._build_carousel_items",
        side_effect=RuntimeError("database password leaked"),
    )
    @mock.patch("api.exceptions.logger.exception")
    def test_unexpected_error_is_logged_and_sanitized(
        self,
        log_exception_mock,
        build_items_mock,
    ):
        response = self.client.get(self.url)

        self.assert_error(
            response,
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
        )
        self.assertEqual(response.data["errors"], {})
        self.assertNotIn("password", response.data["message"])
        log_exception_mock.assert_called_once()
        build_items_mock.assert_called_once_with()
