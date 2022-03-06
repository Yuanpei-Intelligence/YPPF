from typing import Union
from functools import wraps, update_wrapper

from django.db import transaction
from django.contrib import messages
from django.contrib.admin import ModelAdmin
from django.contrib.admin.options import InlineModelAdmin

__all__ = [
    'as_display', 'as_action',
    'perms_check', 'need_all_perms',
    'readonly_inline',
]


def _as_perms(permissions):
    if isinstance(permissions, str):
        return [permissions]
    return permissions


def as_display(description=None, /, register_to=None, *,
               except_value=None, boolean=None, order=None):
    '''
    将函数转化为展示内容的形式，并试图注册(register_to只应是list，否则会出错)
    可以设置输出的形式，异常时的呈现值，呈现顺序等
    '''
    def actual_decorator(action_function):
        @wraps(action_function)
        def _wrapped_display(self: ModelAdmin, obj):
            try:
                return action_function(self, obj)
            except:
                if except_value is None:
                    raise
                return except_value
        if boolean is not None:
            _wrapped_display.boolean = boolean
        if order is not None:
            _wrapped_display.admin_order_field = order
        if description is not None:
            _wrapped_display.short_description = description
        if register_to is not None and _wrapped_display.__name__ not in register_to:
            register_to.append(_wrapped_display.__name__)
        return _wrapped_display
    return actual_decorator


def as_action(description=None, /, register_to=None, permissions=None, *,
              superuser=None, single=False, atomic=False, update=False):
    '''
    将函数转化为操作的形式，并试图注册
    检查用户是否有权限执行操作，有权限时捕获错误
    权限是列表，单个权限可只传入字符串，提供权限要求时默认不检查是否为超级用户
    关键字参数进行检查或启用必要的环境
    '''
    def actual_decorator(action_function):
        nonlocal superuser
        if superuser is None:
            superuser = (permissions is None)

        @wraps(action_function)
        def _wrapped_action(self: ModelAdmin, request, queryset):
            if superuser and not request.user.is_superuser:
                return self.message_user(request=request,
                                         message='操作失败,没有权限,请联系老师!',
                                         level=messages.WARNING)
            if single and len(queryset) != 1:
                return self.message_user(request=request,
                                         message='仅允许操作单个条目!',
                                         level=messages.WARNING)
            try:
                if atomic or update:
                    with transaction.atomic():
                        if update:
                            queryset = queryset.select_for_update()
                        return action_function(self, request, queryset)
                return action_function(self, request, queryset)
            except Exception as e:
                return self.message_user(request=request,
                                         message=f'操作时发生{type(e)}异常: {e}',
                                         level=messages.ERROR)
        if permissions is not None:
            _wrapped_action.allowed_permissions = _as_perms(permissions)
        if description is not None:
            _wrapped_action.short_description = description
        if register_to is not None and _wrapped_action.__name__ not in register_to:
            register_to.append(_wrapped_action.__name__)
        return _wrapped_action
    return actual_decorator


def perms_check(necessary_perms: Union[str, list]=None,
                optional_perms: Union[str, list]=None, *,
                superuser=False):
    '''检查函数，必须具有全部必要权限和至少一个可选权限（如果非空），单个权限可为字符串'''
    def _check_func(self: ModelAdmin, request):
        if superuser and not request.user.is_admin:
            return False
        necessary_checks = (
            getattr(self, f'has_{perm}_permission')
            for perm in _as_perms(necessary_perms) or []
        )
        if not all(has_perm(request) for has_perm in necessary_checks):
            return False
        optional_checks = (
            getattr(self, f'has_{perm}_permission')
            for perm in _as_perms(optional_perms) or []
        )
        if any(has_perm(request) for has_perm in optional_checks):
            return True
        elif optional_checks:
            return False
        return True
    return _check_func


def need_all_perms(necessary_perms: Union[str, list]=None,
                   optional_perms: Union[str, list]=None, *,
                   superuser=False):
    '''包装器，完全取代被包装函数，通过对象的has_$perm$_permission方法检查'''
    def actual_decorator(check_function):
        _check_func = perms_check(
            necessary_perms, optional_perms,
            superuser=superuser,
        )
        update_wrapper(_check_func, check_function)
        return _check_func
    return actual_decorator


def readonly_inline(inline_admin: InlineModelAdmin):
    '''将内联模型设为只读'''
    inline_admin.extra = 0
    inline_admin.can_delete = False
    if hasattr(inline_admin, 'fields'):
        inline_admin.readonly_fields = inline_admin.fields

    def _check_failed(self, request, obj=None):
        return False

    inline_admin.has_add_permission = _check_failed
    inline_admin.has_change_permission = _check_failed
    inline_admin.has_delete_permission = _check_failed
    return inline_admin
