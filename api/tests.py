"""Tests for shared mini-program API infrastructure."""

from unittest import mock

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.test import SimpleTestCase, override_settings
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import BasicAuthentication
from rest_framework.exceptions import (
    AuthenticationFailed,
    ErrorDetail,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from api.exceptions import (
    APIError,
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)


class _NestedItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class _NestedRequestSerializer(serializers.Serializer):
    name = serializers.CharField()
    items = _NestedItemSerializer(many=True)

    def validate(self, attrs):
        raise serializers.ValidationError("组合参数不可用", code="invalid_pair")


class _ExceptionView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [BasicAuthentication]
    permission_classes = []

    def post(self, request):
        kind = request.query_params.get("kind")
        if kind == "validation":
            serializer = _NestedRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
        if kind == "multiple_errors":
            raise ValidationError(
                {
                    "name": [
                        ErrorDetail("名称不能为空。", code="blank"),
                        ErrorDetail("名称格式无效。", code="invalid"),
                    ]
                }
            )
        if kind == "authentication":
            raise AuthenticationFailed("raw authentication detail")
        if kind == "not_authenticated":
            raise NotAuthenticated()
        if kind == "permission":
            raise PermissionDenied("仅负责人可操作。")
        if kind == "django_permission":
            raise DjangoPermissionDenied("Django 权限拒绝。")
        if kind == "not_found":
            raise NotFound("记录不存在。")
        if kind == "django_not_found":
            raise Http404("Django 记录不存在。")
        if kind == "throttled":
            raise Throttled(wait=12)
        if kind == "api_error":
            raise APIError(
                code="activity.capacity_full",
                message="活动名额已满。",
                status_code=status.HTTP_409_CONFLICT,
                errors={
                    "activity": [
                        {"code": "capacity_full", "message": "没有剩余名额。"}
                    ]
                },
            )
        if kind == "unexpected":
            raise RuntimeError("database password must not leak")
        return Response({"ok": True})


class _StandardizedViewSet(
    StandardizedExceptionHandlerMixin,
    viewsets.ViewSet,
):
    authentication_classes = []
    permission_classes = []

    def list(self, request):
        raise NotFound("列表不存在。")


class _LegacyView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        raise ValidationError({"name": "旧格式"})


class _BasicAuthenticationView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [BasicAuthentication]
    permission_classes = []

    def get(self, request):
        raise NotAuthenticated()


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    }
)
class StandardizedExceptionHandlerTests(SimpleTestCase):
    """Exercise the opt-in handler through DRF's normal dispatch path."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = _ExceptionView.as_view()

    def post(self, kind, data=None):
        request = self.factory.post(
            f"/test/?kind={kind}",
            data if data is not None else {},
            format="json",
        )
        return self.view(request)

    def assert_error(self, response, expected_status, expected_code):
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(set(response.data), {"code", "message", "errors"})
        self.assertEqual(response.data["code"], expected_code)
        self.assertIsInstance(response.data["message"], str)
        self.assertIsInstance(response.data["errors"], dict)
        serializer = APIErrorResponseSerializer(data=response.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_nested_validation_errors_keep_paths_and_codes(self):
        response = self.post(
            "validation",
            {
                "items": [
                    {"quantity": 0},
                    {},
                ]
            },
        )

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        self.assertEqual(
            response.data["errors"]["name"][0]["code"],
            "required",
        )
        self.assertEqual(
            response.data["errors"]["items.0.quantity"][0]["code"],
            "min_value",
        )
        self.assertEqual(
            response.data["errors"]["items.1.quantity"][0]["code"],
            "required",
        )

    def test_non_field_error_keeps_its_code(self):
        response = self.post(
            "validation",
            {"name": "test", "items": [{"quantity": 1}]},
        )

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        self.assertEqual(
            response.data["errors"]["non_field_errors"],
            [{"code": "invalid_pair", "message": "组合参数不可用"}],
        )

    def test_multiple_errors_for_one_field_are_preserved(self):
        response = self.post("multiple_errors")

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        self.assertEqual(
            response.data["errors"]["name"],
            [
                {"code": "blank", "message": "名称不能为空。"},
                {"code": "invalid", "message": "名称格式无效。"},
            ],
        )

    def test_authentication_failure_is_invalid_token(self):
        response = self.post("authentication")

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, "invalid_token")
        self.assertNotIn("raw authentication detail", response.data["message"])

    def test_not_authenticated_is_distinct_from_invalid_token(self):
        response = self.post("not_authenticated")

        self.assert_error(
            response,
            status.HTTP_401_UNAUTHORIZED,
            "not_authenticated",
        )

    def test_permission_and_not_found_keep_safe_messages(self):
        permission = self.post("permission")
        missing = self.post("not_found")

        self.assert_error(
            permission,
            status.HTTP_403_FORBIDDEN,
            "permission_denied",
        )
        self.assertEqual(permission.data["message"], "仅负责人可操作。")
        self.assert_error(missing, status.HTTP_404_NOT_FOUND, "not_found")
        self.assertEqual(missing.data["message"], "记录不存在。")

    def test_django_permission_and_http404_are_standardized(self):
        permission = self.post("django_permission")
        missing = self.post("django_not_found")

        self.assert_error(
            permission,
            status.HTTP_403_FORBIDDEN,
            "permission_denied",
        )
        self.assertEqual(permission.data["message"], "Django 权限拒绝。")
        self.assert_error(missing, status.HTTP_404_NOT_FOUND, "not_found")
        self.assertEqual(missing.data["message"], "Django 记录不存在。")

    def test_custom_api_error_preserves_contract(self):
        response = self.post("api_error")

        self.assert_error(
            response,
            status.HTTP_409_CONFLICT,
            "activity.capacity_full",
        )
        self.assertEqual(response.data["message"], "活动名额已满。")
        self.assertEqual(
            response.data["errors"]["activity"],
            [{"code": "capacity_full", "message": "没有剩余名额。"}],
        )

    def test_throttled_preserves_retry_after_header(self):
        response = self.post("throttled")

        self.assert_error(
            response,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "throttled",
        )
        self.assertEqual(response["Retry-After"], "12")

    def test_authentication_header_is_preserved(self):
        response = _BasicAuthenticationView.as_view()(
            self.factory.get("/test/")
        )

        self.assert_error(
            response,
            status.HTTP_401_UNAUTHORIZED,
            "not_authenticated",
        )
        self.assertTrue(response["WWW-Authenticate"].startswith("Basic"))

    def test_unexpected_error_is_logged_and_sanitized(self):
        with mock.patch("api.exceptions.logger.exception") as log_exception:
            response = self.post("unexpected")

        self.assert_error(
            response,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
        )
        self.assertNotIn("password", response.data["message"])
        log_exception.assert_called_once()

    def test_mixin_supports_viewsets(self):
        response = _StandardizedViewSet.as_view({"get": "list"})(
            self.factory.get("/test/")
        )

        self.assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")

    def test_method_not_allowed_is_standardized(self):
        response = self.view(self.factory.get("/test/"))

        self.assert_error(
            response,
            status.HTTP_405_METHOD_NOT_ALLOWED,
            "method_not_allowed",
        )

    def test_view_without_mixin_keeps_native_drf_error(self):
        response = _LegacyView.as_view()(self.factory.get("/test/"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(response.data["name"]), "旧格式")
        self.assertNotIn("code", response.data)

    def test_success_response_is_not_wrapped(self):
        response = self.post("success")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"ok": True})

    def test_api_error_rejects_success_status(self):
        with self.assertRaisesMessage(
            ValueError,
            "APIError status_code must be between 400 and 599",
        ):
            APIError(status_code=status.HTTP_200_OK)
