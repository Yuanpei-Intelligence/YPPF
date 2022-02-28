from functools import wraps
from django.db import transaction
from django.contrib import messages
from django.contrib.admin import ModelAdmin

__all__ = [
    'as_display', 'as_action',
    'need_all_perms',
]


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


def as_action(description=None, /, register_to=None, *,
              superuser=True, single=False, atomic=False, update=False):
    '''
    将函数转化为操作的形式，并试图注册
    检查用户是否有权限执行操作，有权限时捕获错误
    关键字参数进行检查或启用必要的环境
    '''
    def actual_decorator(action_function):
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
        if description is not None:
            _wrapped_action.short_description = description
        if register_to is not None and _wrapped_action.__name__ not in register_to:
            register_to.append(_wrapped_action.__name__)
        return _wrapped_action
    return actual_decorator


def need_all_perms(necessary_perms=None, optional_perms=None):
    '''包装器，完全取代被包装函数，通过对象的has_$perm$_permission方法检查'''
    def actual_decorator(check_function):
        @wraps(check_function)
        def _check_func(self: ModelAdmin, request, obj=None):
            for perm in necessary_perms or []:
                check_func = self.get_attr(f'has_{perm}_permission')
                if not check_func(request, obj):
                    return False
            for perm in optional_perms or []:
                check_func = self.get_attr(f'has_{perm}_permission')
                if check_func(request, obj):
                    return True
            return True
        return _check_func
    return actual_decorator
