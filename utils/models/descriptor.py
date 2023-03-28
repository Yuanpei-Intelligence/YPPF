from typing import Callable, TypeVar, overload

from django.db.models import Field


__all__ = [
    'necessary_for_frontend',
    'invalid_for_frontend',
    'debug_only',
]

T = TypeVar('T')

@overload
def necessary_for_frontend(*fields: str | Field) -> Callable[[T], T]: ...
@overload
def necessary_for_frontend(method: T) -> T: ...

def necessary_for_frontend(method: T | str | Field, *fields: str | Field):
    '''前端必须使用此方法代替直接访问相关属性，如限制choice的属性，可以在参数中标记相关字段'''
    if isinstance(method, (str, Field)):
        return necessary_for_frontend
    return method


def invalid_for_frontend(method: T) -> T:
    '''前端不能使用这个方法'''
    return method


def debug_only(method: T) -> T:
    '''仅用于提供调试信息，如报错、后台、日志记录等，必须对用户不可见'''
    return method
