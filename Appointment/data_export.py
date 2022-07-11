from Appointment.models import Appoint

import pandas as pd
from typing import Callable
from datetime import datetime

__all__ = [
    'appointment_data',
]


def appointment_data(start_time: datetime = None, 
                     end_time: datetime = None, 
                     hash_func: Callable = None) -> pd.DataFrame:
    """
    获取地下室预约的所有数据，返回一个时间从start_time到end_time的DataFrame。
    预约信息包含：预约房间、预约人、参与者、开始时间、结束时间、预约用途。

    :param start_time: 预约记录的起始时间, defaults to None（对起始时间无限制）
    :type start_time: datetime, optional
    :param end_time: 预约记录的终止时间, defaults to None（对终止时间无限制）
    :type end_time: datetime, optional
    :param hash_func: 进行数据脱敏的hash函数, defaults to None（不进行数据脱敏）
    :type hash_func: Callable, optional
    :return: 记录地下室预约数据的DataFrame
    :rtype: pd.DataFrame
    """

    appoint_queryset = Appoint.objects.all()
    if start_time is not None:
        appoint_queryset = appoint_queryset.filter(Astart__gte=start_time)
    if end_time is not None:
        appoint_queryset = appoint_queryset.filter(Astart__lte=end_time)

    appointments = pd.DataFrame(columns=(
        "预约房间", "预约人", "参与者", "开始时间", "结束时间", "预约用途"
    ))
    if appoint_queryset.count() == 0:
        return appointments  # empty dafaframe
    for appoint in appoint_queryset:
        appointments.loc[len(appointments.index)] = [
            appoint.Room.Rid.strip('"') + " " + appoint.Room.Rtitle.strip('"'),  # 预约房间
            hash_func(str(appoint.major_student.Sid)) if hash_func is not None \
                               else appoint.major_student.name,                  # 预约人
            ','.join([hash_func(str(student.Sid)) if hash_func is not None \
                               else student.name for student in appoint.students.all()]),  # 参与者
            appoint.Astart.strftime("%Y年%m月%d日 %H:%M"),    # 开始时间
            appoint.Afinish.strftime("%Y年%m月%d日 %H:%M"),   # 结束时间
            appoint.Ausage,                                  # 预约用途
        ]
    return appointments
