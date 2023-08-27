'''接口描述符

本模块实现模型接口描述符，用于标记模型属性、方法的性质，并提供处理方法。

Note:
- 私密性顺序：公开(前端可用) > 前端不可用 > 仅管理员可用(后端相同) > 仅用于调试(命令行)
- 接口除字符串方法外均默认公开，即前端可用，后端可用，但可以通过标记接口为私有。
- 字符串方法应为管理员可用
'''
from typing import Callable, TypeVar, overload, Any

from django.db.models import Field, Model


__all__ = [
    # 描述符
    'necessary_for_frontend',
    'invalid_for_frontend',
    'admin_only',
    'debug_only',
    # 处理方法
    'export_to_frontend',
]

T = TypeVar('T')

@overload
def necessary_for_frontend(*fields: str | Field) -> Callable[[T], T]: ...
@overload
def necessary_for_frontend(method: T) -> T: ...

def necessary_for_frontend(method: T | str | Field, *fields: str | Field):
    '''前端必须使用此方法代替直接访问相关属性，如限制choice的属性，可以在参数中标记相关字段'''
    if isinstance(method, (str, Field)):
        def _wrapper(*args):
            return necessary_for_frontend(*args, method, *fields)
        return _wrapper
    method.frontend_available = True  # type: ignore
    method.frontend_cover_fields = fields  # type: ignore
    return method


def invalid_for_frontend(method: T) -> T:
    '''前端不能使用这个方法'''
    method.frontend_available = False  # type: ignore
    return method


def admin_only(method: T) -> T:
    '''仅管理员用户可用，如后台、管理员操作的其他页面等，必须对用户不可见'''
    method.frontend_available = 'admin'  # type: ignore
    return method


def debug_only(method: T) -> T:
    '''仅用于提供调试信息，如报错、后台、日志记录等，必须对用户不可见'''
    method.frontend_available = 'debug'  # type: ignore
    return method


def _data_object(datas: dict) -> object:
    '''将字典转换为对象，用于导出数据，支持__str__方法'''
    class Data:
        # str调用type(self).__str__，而不是getattr(self, '__str__')，需要重写
        __str__ = lambda self: datas['__str__']() if '__str__' in datas else '***'
        __repr__ = lambda self: self.__str__()
    data = Data()
    for k, v in datas.items():
        setattr(data, k, v)
    return data


def export_to_frontend(
    instance: Model | Any, *,
    keep_fields: bool = False,
    recursive: bool = False,
) -> object:
    '''将模型实例导出为前端可用的数据结构，仅保留前端允许使用的接口
    
    Args:
    - instance: 模型实例

    Keyword Args:
    - keep_fields: 是否默认保留字段数据，若为True，则默认保留，否则仅保留方法和属性
    - recursive: 是否递归导出，若为True，则关联字段也会被导出，否则仅保留原始模型实例

    Returns:
    - frontend_data: 前端可用的数据结构，移除被标记应替代或删除的字段，后端请勿使用

    Warning:
    - 会访问模型实例的所有属性，关联字段因此会被查询，可能导致性能问题
    - 仅支持导出模型实例，不支持导出QuerySet
    '''
    if not isinstance(instance, Model):
        return instance
    datas = {}
    cover_fields = set()
    for name in dir(instance):
        if name.startswith('_') and name != '__str__':
            continue
        value = getattr(instance, name)
        if getattr(value, 'frontend_cover_fields', None) is not None:
            fields: tuple[str | Field, ...] = value.frontend_cover_fields
            fields = tuple(f if isinstance(f, str) else f.attname for f in fields)
            cover_fields.update(fields)
        available = getattr(value, 'frontend_available', None)
        match available:
            case None:
                # 非私有方法、属性、字段（参数允许时），默认均可用
                available = not name.startswith('_') and (
                    callable(value) or isinstance(value, property) or keep_fields
                )
            case 'admin':
                # 仅管理员可用的方法，在前端暂无需求，不导出
                continue
            case 'debug':
                continue
        if available is True:
            datas[name] = value
    datas = {k: export_to_frontend(v, keep_fields=keep_fields) if recursive else v
             for k, v in datas.items() if k not in cover_fields}
    return _data_object(datas)
