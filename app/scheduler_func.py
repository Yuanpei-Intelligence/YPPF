from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job


from django.http import JsonResponse, HttpResponse  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库

from app.models import Organization, NaturalPerson, Scheduled_YQPoint_Distribute

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")

'''
@register_job(scheduler, 'cron', id='test', day=1, hour=15, minute=23)
def test():
    # 具体要执行的代码
    print("\n\n\nthis is a test register job!\n\n\n")
'''


@register_job(scheduler, 'cron', id='monthly_distribute_YQPoint', day=31, hour=16, minute=2, second=55)
def monthly_distribute_YQPoint():
    try:
        distributer = Scheduled_YQPoint_Distribute.objects.get(type=Scheduled_YQPoint_Distribute.Schedule_Type.MONTH,
            status=Scheduled_YQPoint_Distribute.Distribute_Status.Yes)
        print(distributer)
        
    except Exception as e:
        print("\n按月发放元气值失败，原因可能是没有状态为YES或者有多个状态为YES的发放实例\n" + str(e))

    # 没有问题，找到要发放元气值的人和组织
    per_to_dis = NaturalPerson.objects.activated().filter(
        YQPoint__lte=distributer.per_max_YQPoint)
    org_to_dis = Organization.objects.activated().filter(
        YQPoint__lte=distributer.org_max_YQPoint).exclude(oname="元培学院")
    print(org_to_dis)

    # 计算发放给每个人/组织的多少
    college = Organization.objects.get(oname="元培学院")
    per_get_YQPoint = distributer.per_YQPoint_rate * \
        college.YQPoint / per_to_dis.count()
    org_get_YQPoint = distributer.org_YQPoint_rate * \
        college.YQPoint / org_to_dis.count()

    # 更改并写入数据库
