from typing import TypeAlias, TypeVar

from django.db.models import TextChoices, QuerySet, Model
from utils.models.choice import choice


__all__ = [
    'Semester',
    'select_current',
]


T = TypeVar('T', bound=Model)
AnySemester: TypeAlias = 'Semester | str'


class Semester(TextChoices):
    FALL = choice('Fall', '秋')
    SPRING = choice('Spring', '春')
    ANNUAL = choice('Fall+Spring', '春秋')

    @classmethod
    def get(cls, semester: AnySemester) -> 'Semester':
        '''将一个表示学期的字符串转为返回相应的状态'''
        match semester:
            case Semester():
                return semester
            case 'Fall' | '秋' | '秋季':
                return Semester.FALL
            case 'Spring' | '春' | '春季':
                return Semester.SPRING
            case 'Annual' | 'Fall+Spring' | '全年' | '春秋':
                return Semester.ANNUAL
            case _:
                raise ValueError(f'{semester}不是合法的学期状态')


def select_current(queryset: QuerySet[T], /,
                   year_field: str = 'year', semester_field: str = 'semester', *,
                   noncurrent: bool | None = False, exact: bool = False):
    '''
    获取学期的对应筛选结果
        exact: 学期必须完全匹配(全年和单一学期将不再匹配)
        noncurrent: 取反结果, 如果为None则直接返回queryset.all()
    '''
    if noncurrent is None:
        return queryset.all()
    from boot.config import GLOBAL_CONFIG
    kwargs = {}
    kwargs[year_field] = GLOBAL_CONFIG.acadamic_year
    if not exact:
        semester_field += '__contains'
    kwargs[semester_field] = GLOBAL_CONFIG.semester.value
    return queryset.exclude(**kwargs) if noncurrent else queryset.filter(**kwargs)
