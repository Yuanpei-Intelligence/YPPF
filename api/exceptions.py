"""Opt-in exception handling for mini-program REST APIs.

Views adopt the standardized response contract by placing
``StandardizedExceptionHandlerMixin`` before their DRF base class.  The
handler is intentionally not configured globally while legacy API endpoints
still expose several different error formats.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import serializers, status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    ErrorDetail,
    MethodNotAllowed,
    NotAcceptable,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    UnsupportedMediaType,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger(__name__)


class APIErrorItemSerializer(serializers.Serializer):
    """One machine-readable and user-facing field error."""

    code = serializers.CharField(
        help_text="Stable machine-readable field error code",
    )
    message = serializers.CharField(
        help_text="Safe user-facing field error message",
    )


class APIErrorResponseSerializer(serializers.Serializer):
    """Shared OpenAPI schema for standardized API errors."""

    code = serializers.CharField(
        help_text="Stable machine-readable top-level error code",
    )
    message = serializers.CharField(
        help_text="Safe concise user-facing error message",
    )
    errors = serializers.DictField(
        child=serializers.ListField(child=APIErrorItemSerializer()),
        help_text=(
            "Field-path error mapping; use non_field_errors for errors that "
            "do not belong to one field"
        ),
    )


def _is_error_item(value: Any) -> bool:
    """Return whether a mapping already has the canonical item shape."""

    return (
        isinstance(value, Mapping)
        and set(value.keys()) == {"code", "message"}
    )


def _error_item(value: Any) -> dict[str, str]:
    """Convert a DRF or explicit error value to the canonical item shape."""

    if _is_error_item(value):
        return {
            "code": str(value["code"]),
            "message": str(value["message"]),
        }
    if isinstance(value, ErrorDetail):
        return {"code": str(value.code), "message": str(value)}
    return {"code": "invalid", "message": str(value)}


def _join_path(path: str, part: Any) -> str:
    """Join serializer keys and list indexes into a dotted field path."""

    text = str(part)
    return f"{path}.{text}" if path else text


def _flatten_errors(
    detail: Any,
    *,
    path: str,
    result: dict[str, list[dict[str, str]]],
) -> None:
    """Flatten nested DRF validation details into field-path error lists."""

    if _is_error_item(detail) or isinstance(detail, (str, ErrorDetail)):
        key = path or "non_field_errors"
        result.setdefault(key, []).append(_error_item(detail))
        return

    if isinstance(detail, Mapping):
        if not detail:
            return
        for key, value in detail.items():
            _flatten_errors(
                value,
                path=_join_path(path, key),
                result=result,
            )
        return

    if isinstance(detail, Sequence) and not isinstance(
        detail, (bytes, bytearray)
    ):
        if not detail:
            return
        if all(
            _is_error_item(item) or isinstance(item, (str, ErrorDetail))
            for item in detail
        ):
            key = path or "non_field_errors"
            result.setdefault(key, []).extend(
                _error_item(item) for item in detail
            )
            return
        for index, item in enumerate(detail):
            _flatten_errors(
                item,
                path=_join_path(path, index),
                result=result,
            )
        return

    key = path or "non_field_errors"
    result.setdefault(key, []).append(_error_item(detail))


def normalize_errors(detail: Any) -> dict[str, list[dict[str, str]]]:
    """Return canonical field errors for DRF or explicitly supplied details."""

    result: dict[str, list[dict[str, str]]] = {}
    _flatten_errors(detail, path="", result=result)
    return result


class APIError(APIException):
    """Expected API failure with a stable code and safe public message.

    Feature code should normally raise a semantic subclass when an error is
    reused.  One-off boundary translations may instantiate this class with an
    explicit code and status.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "api_error"
    default_detail = "请求失败。"

    def __init__(
        self,
        *,
        code: str | None = None,
        message: str | None = None,
        status_code: int | None = None,
        errors: Any | None = None,
    ) -> None:
        if status_code is not None:
            if not 400 <= status_code <= 599:
                raise ValueError("APIError status_code must be between 400 and 599")
            self.status_code = status_code

        self.error_code = code or str(self.default_code)
        self.error_message = message or str(self.default_detail)
        self.field_errors = normalize_errors(errors) if errors else {}
        super().__init__(detail=self.error_message, code=self.error_code)


def _first_message(detail: Any) -> str:
    """Extract a concise message from a nested native exception detail."""

    if isinstance(detail, Mapping):
        for value in detail.values():
            message = _first_message(value)
            if message:
                return message
        return ""
    if isinstance(detail, Sequence) and not isinstance(
        detail, (str, bytes, bytearray)
    ):
        for value in detail:
            message = _first_message(value)
            if message:
                return message
        return ""
    return str(detail) if detail is not None else ""


def _standard_error(exc: Exception) -> tuple[str, str]:
    """Map native DRF exceptions to stable codes and safe messages."""

    if isinstance(exc, APIError):
        return exc.error_code, exc.error_message
    if isinstance(exc, NotAuthenticated):
        return "not_authenticated", "请先登录。"
    if isinstance(exc, AuthenticationFailed):
        return "invalid_token", "登录状态无效或已过期。"
    if isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        detail = exc.detail if isinstance(exc, PermissionDenied) else str(exc)
        return (
            "permission_denied",
            _first_message(detail) or "无权执行此操作。",
        )
    if isinstance(exc, (NotFound, Http404)):
        detail = exc.detail if isinstance(exc, NotFound) else str(exc)
        return "not_found", _first_message(detail) or "请求的内容不存在。"
    if isinstance(exc, MethodNotAllowed):
        return "method_not_allowed", "请求方法不受支持。"
    if isinstance(exc, NotAcceptable):
        return "not_acceptable", "无法生成客户端可接受的响应格式。"
    if isinstance(exc, UnsupportedMediaType):
        return "unsupported_media_type", "请求内容类型不受支持。"
    if isinstance(exc, ParseError):
        return "parse_error", "请求内容无法解析。"
    if isinstance(exc, Throttled):
        return "throttled", "请求过于频繁，请稍后重试。"
    if isinstance(exc, ValidationError):
        return "validation_error", "请求参数有误。"
    if isinstance(exc, APIException):
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else str(exc.default_code)
        return code, _first_message(exc.detail) or "请求失败。"
    return "internal_error", "服务器暂时无法处理该请求。"


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """Return the standardized envelope for an opted-in DRF view."""

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled exception in standardized API view")
        return Response(
            {
                "code": "internal_error",
                "message": "服务器暂时无法处理该请求。",
                "errors": {},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code, message = _standard_error(exc)
    if isinstance(exc, APIError):
        errors = exc.field_errors
    elif isinstance(exc, ValidationError):
        errors = normalize_errors(exc.detail)
    else:
        errors = {}

    # Mutating the native response preserves headers such as
    # WWW-Authenticate and Retry-After.
    response.data = {
        "code": code,
        "message": message,
        "errors": errors,
    }
    return response


class StandardizedExceptionHandlerMixin:
    """Opt a DRF APIView or ViewSet into the standardized error contract."""

    def get_exception_handler(self):
        return api_exception_handler


__all__ = [
    "APIError",
    "APIErrorItemSerializer",
    "APIErrorResponseSerializer",
    "StandardizedExceptionHandlerMixin",
    "api_exception_handler",
    "normalize_errors",
]
