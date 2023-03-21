from django.db.models import Field


__all__ = [
    'necessary_for_frontend',
    'invalid_for_frontend',
    'debug_only',
]


def necessary_for_frontend(method, *fields: str | Field):
    '''前端必须使用此方法代替直接访问相关属性，如限制choice的属性，可以在参数中标记相关字段'''
    if isinstance(method, (str, Field)):
        return necessary_for_frontend
    return method


def invalid_for_frontend(method):
    '''前端不能使用这个方法'''
    return method


def debug_only(method):
    '''仅用于提供调试信息，如报错、后台、日志记录等，必须对用户不可见'''
    return method
