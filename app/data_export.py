import pandas as pd
from app.models import (
    Organization,
    Activity,
    Position,
)
import pandas as pd
from typing import Callable
from datetime import datetime


__all__ = [
    'organization_data',
]


def organization_data(start_time: datetime = None, 
                     end_time: datetime = None, 
                     hash_func: Callable = None ) -> pd.DataFrame:
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
    orga_queryset = Organization.objects.all()
    activity_queryset = Activity.objects.all()
    acti_frame = pd.DataFrame(columns=(
        "组织", "活动个数", "活动", "参与人数", "开始时间", "结束时间"
    ))
    # 按时间筛选
    if start_time:
        activity_queryset = activity_queryset.filter(start__gte=start_time)
    if end_time :
        activity_queryset = activity_queryset.filter(start__lte=end_time)

    orga_num = orga_queryset.count()
    acti_allnum = 0 # 总活动个数
    # 便历各个organization
    for orga in orga_queryset:
        orga_acti_queryset = activity_queryset.filter(organization_id=orga)
        acti_num = orga_acti_queryset.count()
        acti_allnum += acti_num
        if  acti_num == 0: # 若没有活动，用/填充
            acti_frame.loc[len(acti_frame.index)] = [
                orga.oname, 0,
                "/","/","/","/"
            ]
            continue
        for acti in orga_acti_queryset:
            acti_frame.loc[len(acti_frame.index)] = [
                orga.oname,
                acti_num,
                acti.title,
                acti.current_participants,
                acti.start.strftime("%Y年%m月%d日 %H:%M"),    # 开始时间
                acti.end.strftime("%Y年%m月%d日 %H:%M"),   # 结束时间
            ]
    # 最后两行输出组织个数和活动个数
    acti_frame.loc[len(acti_frame.index)] = [
        '组织个数', orga_num,
        "/","/","/","/" 
    ]
    acti_frame.loc[len(acti_frame.index)] = [
        '活动个数', acti_allnum,
        "/","/","/","/" 
    ]
    return acti_frame


def orga_position_data(start_time: datetime = None, 
                     end_time: datetime = None, 
                     hash_func: Callable = None) -> pd.DataFrame:
    """导出：每个人参与了什么书院组织

    :param start_time: 筛选的起始时间, defaults to None
    :type start_time: datetime, optional
    :param end_time: 筛选的终止时间, defaults to None
    :type end_time: datetime, optional
    :param hash_func: 脱敏函数, defaults to None
    :type hash_func: Callable, optional
    :return: 返回数据
    :rtype: pd.DataFrame
    """
    person_frame = pd.DataFrame(columns=(
        "学号", "姓名", "参与组织个数", "参与组织",
    ))
    position_queryset = Position.objects.filter(
        status=Position.Status.INSERVICE)  # 只筛选在职的人员
    data_dict = {}
    position_queryset_len = len(position_queryset)
    # 遍历所有position
    for index in range(position_queryset_len):
        position:Position = position_queryset[index]
        personid = position.person.person_id.username  # 学号
        # data_dict[personid][0]为姓名
        # data_dict[personid][1]为储存参加组织的名称的列表
        if data_dict.get(personid):
            data_dict[personid][1].append(position.org.oname)
        else:
            data_dict[personid] = [position.person.name,[position.org.oname,]]
    personlist = list(data_dict.keys())
    if not hash_func: # 若不脱敏，则按学号排序
        personlist.sort()
    for person in personlist:
        person_frame.loc[len(person_frame.index)] = [
            hash_func(person) if hash_func else person,
            hash_func(data_dict[person][0]) if hash_func else data_dict[person][0],
            len(data_dict[person][1]),
            ','.join(data_dict[person][1])
        ]
    
    return person_frame
