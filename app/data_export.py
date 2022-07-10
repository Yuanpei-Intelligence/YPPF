from app.constants import *
from app.models import (
    NaturalPerson,
)
from Appointment.models import (
    Appoint,
)
from app.utils import random_code_init, get_user_by_name

import os
import json
import numpy
import pandas as pd
from datetime import datetime

from boottest import local_dict
from django.contrib.auth.models import User
from django.shortcuts import render
from django.db import transaction

__all__ = [
    # utils
    'try_output', 'data_masking',
    # get data
    'appointment_data',
    # export func
    'export_underground',
]


def try_output(msg: str, output_func=None, html=True):
    '''
    工具函数，尝试用output_func输出msg的内容，如output_func为None则直接返回msg
    '''
    if not html:          # 如果不是呈现在html文档，则将<br/>标签换为\n
        msg = msg.replace('<br/>', '\n')

    if output_func is not None:
        output_func(msg)  # output_func不为None，直接用output_func输出msg
        return None
    else:
        return msg        # output_func为None，返回msg的内容

    
def data_masking(sid: str) -> str:
    '''
    数据脱敏工具函数，根据提供的学生学号给出对应的脱敏结果
    '''
    str1 = sid[-3:] + sid[:2] + sid[4]   # 第一步：取学号头2位、第5位和后3位，乱序拼接
    str2 = str1[2:5] + str1[0] + str1[5] + str1[1]  # 第二步：不同数字以固定规则交换
    str3 = str((int(str2) + 674831) % 1000000)    # 第三步：加上一个数实现整体平移
    return "同学" + str3


def appointment_data(require_data_masking: bool) -> list:
    '''
    获取地下室预约的所有数据，返回一个list，其元素为若干记录预约信息的dict
    
    预约信息包含：预约房间、预约人、参与者、开始时间、结束时间、预约用途
    '''
    appoint_queryset = Appoint.objects.all()
    if appoint_queryset.count() == 0:
        return []
    appointments = []
    for appoint in appoint_queryset:
        appointment = {
            "预约房间": appoint.Room.Rid.strip('"') + " " + appoint.Room.Rtitle.strip('"'),
            "预约人": data_masking(str(appoint.major_student.Sid)) if require_data_masking \
                         else appoint.major_student.name,
            "参与者": [],
            "开始时间": appoint.Astart.strftime("%Y年%m月%d日 %H:%M"),
            "结束时间": appoint.Afinish.strftime("%Y年%m月%d日 %H:%M"),
            "预约用途": appoint.Ausage,
        }
        for student in appoint.students.all():
            appointment["参与者"].append(data_masking(str(student.Sid)) if require_data_masking \
                                      else student.name)
        appointments.append(appointment)
    return appointments
    

def export_underground(filepath, output_func=None, html=False, require_data_masking=False):
    '''
    将地下室预约的所有数据导出为json文件，输出/返回导出成功信息
    '''
    appointments = appointment_data(require_data_masking)
    json_appointments = json.dumps(appointments, ensure_ascii=False, indent=1)
    with open(f"test_data/{filepath}", "w", newline='\n') as jsonfile:
        jsonfile.write(json_appointments)
    return try_output("地下室预约信息导出成功！", output_func, html)
