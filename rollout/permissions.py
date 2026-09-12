'''
Guards restricting API endpoints and website views to accounts for which a
feature is enabled. See ``rollout/README.md``.
'''
from functools import wraps

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from rest_framework import exceptions
from rest_framework.permissions import BasePermission

from rollout.api import is_feature_enabled

__all__ = [
    'FEATURE_NOT_ENABLED',
    'FeatureNotEnabled',
    'feature_permission',
    'feature_required',
]


FEATURE_NOT_ENABLED = 'feature_not_enabled'
FEATURE_NOT_ENABLED_MESSAGE = '这个功能还在灰度测试中，暂未向你的账号开放。'


class FeatureNotEnabled(exceptions.PermissionDenied):
    '''
    HTTP 403 for an authenticated account without access to a feature.

    The body follows the ``{code, message, errors}`` envelope parsed by the
    mini program and names the feature, for example
    ``{"code": "feature_not_enabled", "message": "...", "errors": {},
    "feature": "grades"}``.
    '''
    default_code = FEATURE_NOT_ENABLED

    def __init__(self, feature_key: str):
        super().__init__(detail={
            'code': FEATURE_NOT_ENABLED,
            'message': FEATURE_NOT_ENABLED_MESSAGE,
            'errors': {},
            'feature': feature_key,
        })


def feature_permission(feature_key: str) -> type[BasePermission]:
    '''
    Build a DRF permission class requiring a feature to be enabled.

    List it after ``IsAuthenticated``::

        permission_classes = [IsAuthenticated, feature_permission('grades')]

    Unauthenticated requests are refused without raising, so DRF still answers
    them with HTTP 401 and the mini program renews its token. An authenticated
    account without access receives :class:`FeatureNotEnabled` (HTTP 403).
    '''
    class FeaturePermission(BasePermission):
        def has_permission(self, request, view) -> bool:
            user = request.user
            if user is None or not user.is_authenticated:
                return False
            if is_feature_enabled(user, feature_key):
                return True
            raise FeatureNotEnabled(feature_key)

    FeaturePermission.__name__ = f'FeaturePermission[{feature_key}]'
    FeaturePermission.__qualname__ = FeaturePermission.__name__
    return FeaturePermission


def feature_required(feature_key: str):
    '''
    Decorate a website view so that it requires a feature to be enabled.

    Place it below ``login_required`` and ``check_user_access`` so identity and
    onboarding checks still run first. Accounts without access receive the
    standard HTTP 403 response.
    '''
    def decorator(view_function):
        @wraps(view_function)
        def wrapped(request, *args, **kwargs):
            if not is_feature_enabled(request.user, feature_key):
                raise DjangoPermissionDenied(FEATURE_NOT_ENABLED_MESSAGE)
            return view_function(request, *args, **kwargs)
        return wrapped
    return decorator
