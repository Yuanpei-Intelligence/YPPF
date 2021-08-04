from apscheduler.schedulers.background import BackgroundScheduler
from django.dispatch.dispatcher import receiver
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job

from django.db.models import F
from django.http import JsonResponse, HttpResponse  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库

from app.models import Organization, NaturalPerson, Scheduled_YQPoint_Distribute, TransferRecord, User
from app.wechat_send import base_send_wechat

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")

# @register_job(scheduler, 'cron', id='test', day=1, hour=15, minute=23)
# def test():
#     # 具体要执行的代码
#     print("\n\n\nthis is a test register job!\n\n\n")


@register_job(scheduler, 'interval', id='weekly_distribute_YQPoint', weeks=0, seconds=2)
def scheduled_distribute_YQPoint():
    try:
        distributer = Scheduled_YQPoint_Distribute.objects.get(type=Scheduled_YQPoint_Distribute.Schedule_Type.WEEK,
                                                               status=Scheduled_YQPoint_Distribute.Distribute_Status.Yes)

    except Exception as e:
        print("\n按周发放元气值失败，原因可能是没有状态为YES或者有多个状态为YES的发放实例\n" + str(e))
    trans_time = datetime.now()
    time_record = datetime.now()
    # 没有问题，找到要发放元气值的人和组织
    per_to_dis = NaturalPerson.objects.activated().filter(
        YQPoint__lte=distributer.per_max_dis_YQPoint)
    org_to_dis = Organization.objects.activated().filter(
        YQPoint__lte=distributer.org_max_dis_YQPoint).exclude(oname="元培学院")
    # 由学院账号给大家发放
    YPcollege = Organization.objects.get(oname="元培学院")

    print(f"阶段1用时：{(datetime.now()-time_record).seconds}s,{(datetime.now()-time_record).microseconds}ms")
    time_record = datetime.now()
    # 计算发放给每个人/组织的多少，进行更改，写入数据库

    try:
        assert YPcollege.YQPoint >= (per_to_dis.count(
        ) * distributer.per_YQPoints) + (org_to_dis.count() * distributer.org_YQPoints)
    except Exception as e:
        print("\n按周发放元气值失败，原因可能是学院账号的元气值剩余不足\n" + str(e))

    per_to_dis.update(YQPoint=F('YQPoint') + distributer.per_YQPoints)
    YPcollege.YQPoint -= per_to_dis.count() * distributer.per_YQPoints
    org_to_dis.update(YQPoint=F('YQPoint') + distributer.org_YQPoints)
    YPcollege.YQPoint -= org_to_dis.count() * distributer.org_YQPoints
    YPcollege.save()

    print(f"阶段2用时：{(datetime.now()-time_record).seconds}s,{(datetime.now()-time_record).microseconds}ms")
    time_record = datetime.now()

    trans_msg = "haoye!!!"
    print(f"阶段3用时：{(datetime.now()-time_record).seconds}s,{(datetime.now()-time_record).microseconds}ms")
    time_record = datetime.now()
    # 添加转账记录
    transfer_record_lst = []
    for per_id in per_to_dis:
        transfer_record_lst.append(TransferRecord(
            proposer=YPcollege.organization_id,
            recipient=per_id.person_id,
            amount=distributer.per_YQPoints,
            start_time=trans_time,
            finish_time=trans_time,
            message=trans_msg,
            status=TransferRecord.TransferStatus.ACCEPTED
        )
        )
    
    for org in org_to_dis:
        transfer_record_lst.append(TransferRecord(
            proposer=YPcollege.organization_id,
            recipient=org.organization_id,
            amount=distributer.org_YQPoints,
            start_time=trans_time,
            finish_time=trans_time,
            message=trans_msg,
            status=TransferRecord.TransferStatus.ACCEPTED
        )
        )
    

    
    TransferRecord.objects.bulk_create(transfer_record_lst)
    end_time = datetime.now()

    
    debug_msg = f"已向{per_to_dis.count()}个自然人和{org_to_dis.count()}个组织转账，用时{(end_time - trans_time).seconds}s,{(end_time - trans_time).microseconds}microsecond\n"
    print(debug_msg)
