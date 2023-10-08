'''查询引用字段

- 获取查询字段的函数，且同时支持字段描述符、字段实例以及字段名称。
- 通过标记字段为特殊关联字段，可以获取特殊关联字段的查询名称。
- 进行单条件查询的函数，使用首个字段所在模型的默认管理器进行查询。
- 辅助多条件查询的函数，追踪关系并查询字段。

在本模块中，有 s 前缀的函数均为单字段转化函数或单条件查询函数，m 前缀的为多条件查询函数。

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

    对于**名称固定**的最终非关系字段，使用关键字参数查询往往更方便::
        
        instance = queryset.get(mq(BModel.fkey2_name, AModel.fkey_name, field_name=...))

    在默认管理器上进行查询时，可以直接使用查询函数::

        instance = mget(BModel.fkey2_name, AModel.fkey_name, field_name=...)
        names = svlist(BModel.fkey2_name, AModel.fkey_name, field_name)
        blogs = mfilter(Blog.author, Author.user, score=0, active=True)

Warning:
    本模块的函数在模型定义时无法使用，因为字段描述符在模型类创建后才会被创建，但你可以在任何方法中使用。

Note:
    本模块不提供与更新相关的函数，因为更新不会跨越关系，且应以管理器要求的安全方式进行。
    尽管多条件查询支持关键字参数，你仍应避免在条件中包含`__`以阻碍`field=`型字段追踪。
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
    'f', 'q', 'sq', 'mq',
    'Index', 'Forward', 'Reverse',
    'sget', 'sfilter', 'sexclude', 'svalues', 'svlist',
    'qsvlist',
    'mget', 'mfilter', 'mexclude',
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
FieldLikeObject: TypeAlias = FieldLike | SpecialRelation
FieldLikeExpr: TypeAlias = FieldLikeObject | str


def _is_relation(field: FieldLikeObject) -> TypeGuard[RelationLike]:
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


def _to_field_name(field: FieldLikeExpr) -> str:
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


def f(*fields: FieldLikeExpr) -> str:
    '''获取连续字段的查询名称'''
    return LOOKUP_SEP.join(_to_field_name(field) for field in fields)


def q(*fields: FieldLikeExpr, value: Any) -> Q:
    '''获取连续字段的查询Q对象'''
    return Q(**{f(*fields): value})


def mq(*fields: FieldLikeExpr, **querys: Any) -> Q:
    '''获取包含某字段多个查询条件的Q对象
    
    Args:
        *fields: 代表字段的完整路径，可以包含连续字段
        **querys: 查询条件，键为查询类型，值为查询值

    Returns:
        Q: 将每个查询条件`key: value`转为`q(*fields, key, value=value)`的`Q`条件之交

    Example:
        >>> mq('user', 'id', lt=1, gt=0, isnull=False)
        Q(user__id__lt=1, user__id__gt=0, user__id__isnull=False)

    Note:
        尽量避免在查询条件中包含`__`，这严重妨碍了`field=`型字段追踪。
    '''
    prefix = f(*fields)
    if prefix:
        prefix += LOOKUP_SEP
    return Q(**{prefix + key: value for key, value in querys.items()})


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


def sq(field: Extend[FieldLikeExpr], value: Any) -> Q:
    '''获取单个查询条件的Q对象，可以包含连续字段'''
    return q(*_as_seq(field), value=value)


def _get_queryset(field: Extend[FieldLikeObject]) -> QuerySet[Model]:
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


def _ext(fields: Extend[FieldLikeObject]) -> Extend[Any]:
    return fields


def sget(field: Extend[FieldLikeObject], value: Any) -> Any:
    '''单条件获取模型实例，见`QuerySet.get`'''
    return _get_queryset(field).get(sq(_ext(field), value))


def mget(field: FieldLikeObject, *extras: FieldLikeExpr, **querys: Any) -> Any:
    '''多条件获取模型实例，见`QuerySet.get`'''
    return _get_queryset(field).get(mq(field, *extras, **querys))


def sfilter(field: Extend[FieldLikeObject], value: Any) -> QuerySet:
    '''单条件过滤查询集，见`QuerySet.filter`'''
    return _get_queryset(field).filter(sq(_ext(field), value))


def mfilter(field: FieldLikeObject, *extras: FieldLikeExpr, **querys: Any) -> QuerySet:
    '''多条件过滤查询集，见`QuerySet.filter`'''
    return _get_queryset(field).filter(mq(field, *extras, **querys))


def sexclude(field: Extend[FieldLikeObject], value: Any) -> QuerySet:
    '''单条件排除查询集，见`QuerySet.exclude`'''
    return _get_queryset(field).exclude(sq(_ext(field), value))


def mexclude(field: FieldLikeObject, *extras: FieldLikeExpr, **querys: Any) -> QuerySet:
    '''多条件排除查询集，见`QuerySet.exclude`，查询条件为交集'''
    return _get_queryset(field).exclude(mq(field, *extras, **querys))


def svalues(field: FieldLikeObject, *extras: FieldLikeExpr):
    '''单条件查询字段值，见`QuerySet.values`'''
    return _get_queryset(field).values(f(field, *extras))


def qsvlist(queryset: QuerySet, field: FieldLikeExpr, *extras: FieldLikeExpr) -> list[Any]:
    '''单条件查询字段值，立即计算并转为列表，见`QuerySet.values_list`'''
    return list(queryset.values_list(f(field, *extras), flat=True))


def svlist(field: FieldLikeObject, *extras: FieldLikeExpr) -> list[Any]:
    '''单条件查询字段值，立即计算并转为列表，见`QuerySet.values_list`'''
    return qsvlist(_get_queryset(field), field, *extras)
