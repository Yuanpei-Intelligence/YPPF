from typing import TypeAlias

from django.db.models import TextChoices, QuerySet
from utils.models.choice import choice


__all__ = [
    'Semester',
    'current_year',
    'select_current',
]


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

    @classmethod
    def now(cls):
        '''返回本地设置中当前学期对应的Semester状态'''
        from boot.config import GLOBAL_CONFIG
        return GLOBAL_CONFIG.semester



def current_year() -> int:
    '''获取学年设置'''
    from boot.config import GLOBAL_CONFIG
    return GLOBAL_CONFIG.acadamic_year


def select_current(queryset: QuerySet, /,
                   _year_field='year', _semester_field='semester', *,
                   noncurrent: bool = False, exact: bool = False):
    '''
    获取学期的对应筛选结果
        exact: 学期必须完全匹配(全年和单一学期将不再匹配)
        noncurrent: 取反结果, 如果为None则直接返回queryset.all()
    '''
    if noncurrent is None:
        return queryset.all()
    from boot.config import GLOBAL_CONFIG
    kwargs = {}
    kwargs[_year_field] = GLOBAL_CONFIG.acadamic_year
    if not exact:
        _semester_field += '__contains'
    kwargs[_semester_field] = GLOBAL_CONFIG.semester.value
    return queryset.exclude(**kwargs) if noncurrent else queryset.filter(**kwargs)
