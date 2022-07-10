from Appointment.models import Appoint

import pandas as pd
from datetime import datetime

__all__ = [
    'appointment_data',
]


def appointment_data(start_time=None, end_time=None, hash_func=None) -> pd.DataFrame:
    '''
    获取地下室预约的所有数据，返回一个时间从start_time到end_time的DataFrame。
    
    预约信息包含：预约房间、预约人、参与者、开始时间、结束时间、预约用途。
    
    start_time为None表示对记录的起始时间无限制，end_time同理。
    
    hash_func是进行数据脱敏的hash函数，其为None表示不进行数据脱敏。
    '''
    appoint_queryset = Appoint.objects.all()
    if start_time is not None:
        appoint_queryset = appoint_queryset.filter(Atime__gte=start_time)
    if end_time is not None:
        appoint_queryset = appoint_queryset.filter(Atime__lte=end_time)

    if appoint_queryset.count() == 0:
        return pd.DataFrame()  # empty dataframe
    appointments = []
    for appoint in appoint_queryset:
        appointment = {
            "预约房间": appoint.Room.Rid.strip('"') + " " + appoint.Room.Rtitle.strip('"'),
            "预约人": hash_func(str(appoint.major_student.Sid)) if hash_func is not None \
                         else appoint.major_student.name,
            "参与者": "",
            "开始时间": appoint.Astart.strftime("%Y年%m月%d日 %H:%M"),
            "结束时间": appoint.Afinish.strftime("%Y年%m月%d日 %H:%M"),
            "预约用途": appoint.Ausage,
        }
        for student in appoint.students.all():
            appointment["参与者"] += hash_func(str(student.Sid)) + "," if hash_func is not None \
                                      else student.name + ","
        appointment["参与者"] = appointment["参与者"][:-1]  # 去除行末逗号
        appointments.append(appointment)
    return pd.DataFrame(appointments)
