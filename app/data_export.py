from datetime import datetime
from typing import Callable

import pandas as pd
from django.db.models import Aggregate, CharField, Count

from app.models import (
    Activity,
    Position
)

__all__ = [
    'organization_data',
    'orga_position_data',
]


def organization_data(start_time: datetime = None,
                      end_time: datetime = None,
                      hash_func: Callable = None) -> pd.DataFrame:
    """ 导出：组织数量，每个组织办的活动的数量及参与人数。

    :param start_time: 筛选的起始时间, defaults to None
    :type start_time: datetime, optional
    :param end_time: 筛选的终止时间, defaults to None
    :type end_time: datetime, optional
    :param hash_func: 脱敏函数, defaults to None
    :type hash_func: Callable, optional
    :return: 返回数据
    :rtype: pd.DataFrame
    """
    activity_queryset = Activity.objects.all()
    acti_frame = pd.DataFrame(columns=(
        "组织", "活动", "参与人数", "开始时间", "结束时间"
    ))
    # 按时间筛选
    if start_time:
        activity_queryset = activity_queryset.filter(start__gte=start_time)
    if end_time:
        activity_queryset = activity_queryset.filter(start__lte=end_time)
    orga_name = 'organization_id__oname'
    activity_queryset = activity_queryset.values_list(
        orga_name, 'title', 'current_participants', 'start', 'end').order_by(orga_name)

    for acti in activity_queryset:
        acti_frame.loc[len(acti_frame.index)] = [
            acti[0], acti[1], acti[2],
            acti[3].strftime("%Y年%m月%d日 %H:%M"),    # 开始时间
            acti[4].strftime("%Y年%m月%d日 %H:%M"),   # 结束时间
        ]

    return acti_frame


def orga_position_data(start_time: int = None,
                       end_time: int = None,
                       hash_func: Callable = None) -> pd.DataFrame:
    """导出：每个人参与了什么书院组织

    :param start_time: 筛选的起始学年, defaults to None
    :type start_time: int, optional
    :param end_time: 筛选的终止学年, defaults to None
    :type end_time: int, optional
    :param hash_func: 脱敏函数, defaults to None
    :type hash_func: Callable, optional
    :return: 返回数据
    :rtype: pd.DataFrame
    """
    class GroupConcat(Aggregate):  # 用于分类聚合查询
        function = 'GROUP_CONCAT'
        template = '%(function)s(%(distinct)s%(expressions)s%(ordering)s%(separator)s)'

        def __init__(self, expression, distinct=False, ordering=None, separator=',', **extra):
            super(GroupConcat, self).__init__(
                expression,
                distinct='DISTINCT ' if distinct else '',
                ordering=' ORDER BY %s' % ordering if ordering is not None else '',
                separator=' SEPARATOR "%s"' % separator,
                output_field=CharField(),
                **extra
            )
    person_frame = pd.DataFrame(columns=(
        "学号", "参与组织个数", "参与组织",
    ))
    position_queryset = Position.objects.all()
    if start_time:
        position_queryset = position_queryset.filter(in_year__gte=start_time)
    if end_time:
        position_queryset = position_queryset.filter(in_year__lte=end_time)

    sid = "person__person_id__username"  # 学号
    position_queryset = position_queryset.values(sid) \
        .annotate(count=Count('org'), orgalist=GroupConcat('org__oname', separator=",")
                  ).order_by(sid)

    for person in position_queryset:
        person_frame.loc[len(person_frame.index)] = [
            hash_func(person[sid]) if hash_func else person[sid],
            person['count'],
            person['orgalist']
        ]

    return person_frame
