from typing import Union, Callable, Optional
from functools import wraps, update_wrapper

from django.db import transaction
from django.db.models import QuerySet, Model
from django.contrib import messages
from django.contrib.auth import get_permission_codename
from django.contrib.admin import ModelAdmin, SimpleListFilter

from utils.http import HttpRequest

__all__ = [
    'as_display', 'as_action',
    'no_perm', 'has_superuser_permission',
    'inherit_permissions',
    'perms_check', 'need_all_perms',
    'readonly_admin', 'readonly_inline',
    'SimpleSignFilter', 'get_sign_filter',
]


def _as_perms(permissions: 'str | list[str]'):
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


def as_action(description: str = None, /,
              register_to: list = None, permissions: 'str | list[str]' = None, *,
              superuser: bool = None, single: bool = False,
              atomic: bool = False, update: bool = False):
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


PermFunc = Callable[[ModelAdmin, HttpRequest, Optional[Model]], bool]

def no_perm(self: ModelAdmin, request: HttpRequest, obj=None):
    '''总是返回没有权限'''
    return False

def has_superuser_permission(self: ModelAdmin, request: HttpRequest, obj=None):
    '''检查是否为超级用户'''
    return request.user.is_superuser


def has_perm(action: str, model: Model = None) -> PermFunc:
    '''
    检查模型的指定权限

    :param action: 需要检查的权限名
    :type action: str
    :param model: 权限模型, defaults to None
    :type model: Type[Model], optional
    :return: 权限检查函数
    :rtype: PermFunc
    '''
    if model is not None:
        codename = get_permission_codename(action, model._meta)
        perm = f'{model._meta.app_label}.{codename}'
        def _check_func(self: ModelAdmin, request: HttpRequest, obj=None) -> bool:
            return request.user.has_perm(perm)
        return _check_func
    # 否则执行时计算
    def _check_func(self: ModelAdmin, request: HttpRequest, obj=None) -> bool:
        codename = get_permission_codename(action, self.opts)
        return request.user.has_perm(f'{self.opts.app_label}.{codename}')
    return _check_func


def inherit_permissions(model: Model, superuser: bool = True):
    '''
    包装器，根据关联模型，
    被包装的模型的action除四种自带权限以外，还可使用superuser和模型声明的各种权限
    实现细节：为后台自动生成has_%perm%_permission权限检查函数，不覆盖已存在函数

    :param model: 后台的关联模型
    :type model: Type[Model]
    :param superuser: 是否产生has_superuser_permission检查函数, defaults to True
    :type superuser: bool, optional
    '''
    def _actual_wrapper(admin: ModelAdmin):
        for perm in model._meta.permissions:
            check_name = f'has_{perm}_permission'
            if hasattr(admin, check_name):
                continue
            setattr(admin, check_name, has_perm(perm, model))
        if superuser and not hasattr(admin, 'has_superuser_permission'):
            admin.has_superuser_permission = has_superuser_permission
        return admin
    return _actual_wrapper


def perms_check(necessary_perms: Union[str, list]=None,
                optional_perms: Union[str, list]=None, *,
                superuser=False):
    '''检查函数，必须具有全部必要权限和至少一个可选权限（如果非空），单个权限可为字符串'''
    def _check_func(self: ModelAdmin, request: HttpRequest):
        if superuser and not request.user.is_superuser:
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


def readonly_admin(admin: ModelAdmin,
                   inline_attrs: bool = True, can_add: bool = False):
    '''将管理模型设为只读，inline_attrs决定是否设置内联模型相关属性，通常无影响'''
    # 设置内联模型的属性，对通用管理模型无影响，一般都可以设置
    if inline_attrs:
        admin.extra = 0
        admin.can_delete = False
    if not can_add:
        if admin.fields is not None:
            admin.readonly_fields = admin.fields
        admin.has_add_permission = no_perm
    admin.has_change_permission = no_perm
    admin.has_delete_permission = no_perm
    return admin

readonly_inline = readonly_admin

class SimpleSignFilter(SimpleListFilter):
    '''子类必须以field定义筛选的字段，可以定义lookup_choices'''
    title = '符号'
    parameter_name = 'Sign'
    field: str = NotImplemented

    def lookups(self, request, model_admin):
        return getattr(self, 'lookup_choices', (('+', '正'), ('-', '负'), ('=', '零'))) 
    
    def queryset(self, request, queryset: QuerySet):
        if self.value() == '+':
            return queryset.filter(**{self.field + '__gt': 0})
        elif self.value() == '-':
            return queryset.filter(**{self.field + '__lt': 0})
        elif self.value() == '=':
            return queryset.filter(**{self.field + '__exact': 0})
        return queryset


def get_sign_filter(field: str, title: str = None, param_name: str = None,
                    choices: 'tuple[tuple[str, str]]' = None):
    class SignFilter(SimpleSignFilter): pass
    SignFilter.field = field
    if title is not None:
        SignFilter.title = title
    if param_name is not None:
        SignFilter.parameter_name = param_name
    if choices is not None:
        SignFilter.lookup_choices = choices
    return SignFilter
