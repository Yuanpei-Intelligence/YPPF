'''查询引用字段

- 获取查询字段的函数，且同时支持字段描述符、字段实例以及字段名称。
- 通过标记字段为特殊关联字段，可以获取特殊关联字段的查询名称。
- 进行单条件查询的函数，使用首个字段所在模型的默认管理器进行查询。

在本模块中，以 s 开头的函数均为单字段转化函数或单条件查询函数。

在以往的代码中，我们经常会看到这样的代码::

    class AModel(Model):
        fkey_name = models.ForeignKey(...)

    class BModel(Model):
        fkey2_name = models.ForeignKey(A_Model)

当跨越关系查询时，我们需要写很长的代码，这样不仅不美观，而且不利于代码的追踪修改，例如::

    instance = BModel.objects.filter(fkey2_name__fkey_name__field_name=...)
    values = BModel.objects.values('fkey2_name__fkey_name__field_name')

如需修改`fkey2_name`字段的名称，则无法追踪以上代码，因此修改起来非常困难，且容易出错。
这是因为我们使用字符串来引用字段来引用字段。如果我们通过字段本身来引用，就可以避免这个问题。

Example:
    使用`f`和`q`类型函数来获取字段的查询名称和条件，并追踪引用::

        instance = BModel.objects.filter(sq([BModel.fkey2_name, AModel.fkey_name, 'field_name'], ...))
        values = BModel.objects.values(f(BModel.fkey2_name, AModel.fkey_name, 'field_name'))

Warning:
    本模块的函数在模型定义时无法使用，因为字段描述符在模型类创建后才会被创建，但你可以在任何方法中使用。

Note:
    本模块不提供与更新相关的函数，因为更新不会跨越关系，且应以管理器要求的安全方式进行。
'''
from typing import cast, Any, TypeAlias, TypeGuard, TypeVar

from django.db.models import Field, Q, QuerySet, Model
from django.db.models.query_utils import DeferredAttribute
from django.db.models.fields.files import FileDescriptor
from django.db.models.fields.related import RelatedField, ForeignObjectRel
from django.db.models.fields.related_descriptors import (
    ForwardManyToOneDescriptor,
    ForwardOneToOneDescriptor,
    ReverseManyToOneDescriptor,
    ReverseOneToOneDescriptor,
    ManyToManyDescriptor,
    ForeignKeyDeferredAttribute,
)
from django.db.models.constants import LOOKUP_SEP


__all__ = [
    'f', 'q', 'lq', 'sq',
    'Index', 'Forward', 'Reverse',
    'sget', 'sfilter', 'sexclude',
]


NormalFieldDescriptor: TypeAlias = DeferredAttribute | FileDescriptor
NormalFieldLike: TypeAlias = Field | NormalFieldDescriptor
ForwardDescriptor: TypeAlias = ForwardManyToOneDescriptor | ForwardOneToOneDescriptor
ReverseDescriptor: TypeAlias = ReverseManyToOneDescriptor | ReverseOneToOneDescriptor
ForeignIndexDescriptor: TypeAlias = ForeignKeyDeferredAttribute
RelatedDescriptor: TypeAlias = (ForwardDescriptor | ReverseDescriptor
                                | ForeignIndexDescriptor | ManyToManyDescriptor)
RelatedFieldLike: TypeAlias = RelatedField | RelatedDescriptor
FieldLike: TypeAlias = NormalFieldLike | RelatedFieldLike
FieldLikeExpr: TypeAlias = FieldLike | str


class SpecialRelation:
    '''特殊关联字段

    用于标记字段为特殊关联字段，转化查询时使用`fieldlike`属性。
    '''
    def __init__(self, fieldlike: RelatedFieldLike) -> None:
        self.fieldlike = fieldlike


class Index(SpecialRelation):
    '''索引字段

    标记字段为索引字段，查询时转化为`%field_name%_id`。
    '''
    pass


class Forward(SpecialRelation):
    '''正向关系字段

    标记字段为正向关系字段，查询时转化为`%field_name%`。
    '''
    pass


class Reverse(SpecialRelation):
    '''反向关系字段

    标记字段为反向关系字段，查询时转化为`%field_name%`。
    '''
    pass


IndexLike: TypeAlias = ForeignIndexDescriptor | Index
RelationLike: TypeAlias = RelatedFieldLike | SpecialRelation


def _is_relation(field: FieldLike | SpecialRelation) -> TypeGuard[RelationLike]:
    '''判断字段是否为关系字段相关属性'''
    if isinstance(field, SpecialRelation):
        field = field.fieldlike
    if isinstance(field, Field):
        return field.is_relation
    if isinstance(field, RelatedDescriptor):
        return True
    return False


def _is_foreign_index(field: RelationLike) -> TypeGuard[IndexLike]:
    '''判断字段是否为外键索引字段'''
    if isinstance(field, Index):
        return True
    return isinstance(field, ForeignIndexDescriptor)


def _is_forward_relation(field: RelationLike) -> bool:
    '''判断字段是否为正向关系字段'''
    if isinstance(field, ManyToManyDescriptor):
        return not field.reverse
    if isinstance(field, Forward):
        return True
    return isinstance(field, ForwardDescriptor | RelatedField)


def _is_reverse_relation(field: RelationLike) -> bool:
    '''判断字段是否为反向关系字段'''
    if isinstance(field, ManyToManyDescriptor):
        return field.reverse
    if isinstance(field, Reverse):
        return True
    return isinstance(field, ReverseDescriptor)


def _get_normal_field(field: NormalFieldLike) -> Field:
    '''获取普通字段，同样可用于关联字段，但不适用于关联字段描述符'''
    if isinstance(field, NormalFieldDescriptor):
        field = field.field
    if not isinstance(field, Field):
        raise TypeError(f'{type(field)} is not a normal field')
    return field


def _get_related_field(field: RelationLike) -> RelatedField:
    '''获取关系字段'''
    if isinstance(field, SpecialRelation):
        field = field.fieldlike
    if isinstance(field, RelatedField):
        return field
    if isinstance(field, ForeignIndexDescriptor):
        return cast(RelatedField, field.field)
    if isinstance(field, ForwardDescriptor):
        return cast(RelatedField, field.field)
    if isinstance(field, ManyToManyDescriptor):
        return field.field
    if isinstance(field, ReverseOneToOneDescriptor):
        return field.related.field
    if isinstance(field, ReverseManyToOneDescriptor):
        return cast(RelatedField, field.field)
    raise TypeError(f'{type(field)} is not a related field')


def _normal_name(field: NormalFieldLike) -> str:
    '''获取普通字段的查询名称'''
    # 普通字段的`name`属性代表字段在查询时使用的名称
    # 见`Field.get_filter_kwargs_for_object`
    return _get_normal_field(field).name


def _foreign_index_name(field: RelationLike) -> str:
    '''获取外键索引字段的查询名称'''
    # `attname`属性代表`ForeignKey`对应数据库字段的名称，即`%field_name%_id`
    return _get_related_field(field).attname


def _forward_name(field: RelationLike) -> str:
    '''获取正向关系字段的查询名称'''
    # 关联字段的`name`属性代表模型字段的名称
    return _get_related_field(field).name


def _get_reverse_relation(related_field: RelatedField) -> ForeignObjectRel:
    '''获取反向关系字段

    Raises:
        ValueError: 如果反向关系字段不可用
    '''
    rel = cast(ForeignObjectRel, related_field.remote_field)
    if rel.is_hidden():
        raise ValueError(f'Cannot reverse a hidden relation: {related_field}')
    return rel
    

def _reverse_name(field: RelationLike) -> str:
    '''获取反向关系字段的查询名称'''
    # 反向关系字段的`name`属性代表模型字段的名称
    field = _get_related_field(field)
    _get_reverse_relation(field)
    return field.related_query_name()


def _to_field_name(field: FieldLikeExpr | SpecialRelation) -> str:
    '''获取字段的查询名称'''
    if isinstance(field, str):
        return field
    if _is_relation(field):
        if _is_foreign_index(field):
            return _foreign_index_name(field)
        if _is_forward_relation(field):
            return _forward_name(field)
        if _is_reverse_relation(field):
            return _reverse_name(field)
    elif isinstance(field, NormalFieldLike):
        return _normal_name(field)
    raise TypeError(f'Unsupported type: {type(field)} for field')


def f(*fields: FieldLikeExpr | SpecialRelation) -> str:
    '''获取连续字段的查询名称'''
    return LOOKUP_SEP.join(_to_field_name(field) for field in fields)


def q(*fields: FieldLikeExpr | SpecialRelation, value: Any) -> Q:
    '''获取连续字段的查询Q对象'''
    return Q(**{f(*fields): value})


def lq(value: Any, *fields: FieldLikeExpr | SpecialRelation) -> Q:
    '''获取连续字段的查询Q对象，参数线性排列'''
    return q(*fields, value=value)


T = TypeVar('T')
ListLike: TypeAlias = list[T] | tuple[T, ...]
Extend: TypeAlias = T | ListLike[T]


def _as_seq(value: Extend[T]) -> ListLike[T]:
    '''将参数转化成类似列表的序列形式'''
    if not isinstance(value, (list, tuple)):
        value = [value]
    return value


def _first(field: Extend[T]) -> T:
    '''获取字段的第一个元素'''
    fields = _as_seq(field)
    if not fields:
        raise TypeError('Empty fields')
    return fields[0]


def sq(field: Extend[FieldLikeExpr | SpecialRelation], value: Any) -> Q:
    '''获取单个查询条件的Q对象，可以包含连续字段'''
    return q(*_as_seq(field), value=value)


def _get_queryset(field: Extend[FieldLike | SpecialRelation]) -> QuerySet[Model]:
    '''获取字段的查询集'''
    field = _first(field)
    if _is_relation(field):
        if _is_reverse_relation(field):
            rel = _get_reverse_relation(_get_related_field(field))
            return cast(type[Model], rel.model)._default_manager.all()
        field = _get_related_field(field)
    else:
        field = _get_normal_field(field)  # type: ignore
    return field.model._default_manager.all()


def _ext(fields: Extend[FieldLike | SpecialRelation]) -> Extend[Any]:
    return fields


def sget(field: Extend[FieldLike | SpecialRelation], value: Any) -> Model:
    '''单条件获取模型实例，见`QuerySet.get`'''
    return _get_queryset(field).get(sq(_ext(field), value))


def sfilter(field: Extend[FieldLike | SpecialRelation], value: Any) -> QuerySet:
    '''单条件过滤查询集，见`QuerySet.filter`'''
    return _get_queryset(field).filter(sq(_ext(field), value))


def sexclude(field: Extend[FieldLike | SpecialRelation], value: Any) -> QuerySet:
    '''单条件排除查询集，见`QuerySet.exclude`'''
    return _get_queryset(field).exclude(sq(_ext(field), value))
