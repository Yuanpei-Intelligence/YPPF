from typing import cast, Any, TypeAlias

from django.db.models import Field, Q
from django.db.models.query_utils import DeferredAttribute
from django.db.models.constants import LOOKUP_SEP

FieldLikeExpr: TypeAlias = Field | DeferredAttribute | str


def _to_field_name(field: FieldLikeExpr) -> str:
    '''获取字段的查询名称'''
    # 普通字段的`name`属性代表字段在查询时使用的名称，见`Field.get_filter_kwargs_for_object`
    if isinstance(field, DeferredAttribute):
        field = field.field
    if isinstance(field, Field):
        return field.name
    elif isinstance(field, str):
        return field
    raise TypeError(f'Unsupported type: {type(field)} for field')


def f(*fields: FieldLikeExpr) -> str:
    '''获取连续字段的查询名称'''
    return LOOKUP_SEP.join(_to_field_name(field) for field in fields)


def q(*fields: FieldLikeExpr, value: Any) -> Q:
    '''获取连续字段的查询Q对象'''
    return Q(**{f(*fields): value})


def lq(value: Any, *fields: FieldLikeExpr) -> Q:
    '''获取连续字段的查询Q对象，参数线性排列'''
    return q(*fields, value=value)
