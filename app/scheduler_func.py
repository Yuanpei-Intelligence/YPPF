'''
scheduler_func.py

应尽量只包含周期性定时任务
'''
from app.models import (
    User,
    NaturalPerson,
    Organization,
    TransferRecord,
    Activity,
    Participant,
    Notification,
    Position,
)
from app.activity_utils import changeActivityStatus
from app.notification_utils import bulk_notification_create, notification_status_change
from app.wechat_send import publish_notifications, WechatMessageLevel, WechatApp
from app import log
from app.constants import *
from boottest import local_dict

import json
import urllib.request

from datetime import datetime, timedelta
from django.db import transaction  # 原子化更改数据库

# 引入定时任务还是放上面吧
from app.scheduler import scheduler

default_weather = get_config('default_weather', default=None)


def send_to_persons(title, message, url='/index/'):
    sender = User.objects.get(username='zz00000')
    np = NaturalPerson.objects.activated().all()
    receivers = User.objects.filter(id__in=np.values_list('person_id', flat=True))
    print(bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT},
        ))


def send_to_orgs(title, message, url='/index/'):
    sender = User.objects.get(username='zz00000')
    org = Organization.objects.activated().all().exclude(otype__otype_id=0)
    receivers = User.objects.filter(id__in=org.values_list('organization_id', flat=True))
    bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT},
        )


# 学院每月下发元气值
def distribute_YQPoint_per_month():
    with transaction.atomic():
        recipients = NaturalPerson.objects.activated().select_for_update()
        YP = Organization.objects.get(oname=YQP_ONAME)
        trans_time = datetime.now()
        transfer_list = [TransferRecord(
                proposer=YP.organization_id,
                recipient=recipient.person_id,
                amount=(30 + max(0, (30 - recipient.YQPoint))),
                start_time=trans_time,
                finish_time=trans_time,
                message=f"元气值每月发放。",
                status=TransferRecord.TransferStatus.ACCEPTED,
                rtype=TransferRecord.TransferType.BONUS
        ) for recipient in recipients]
        notification_lists = [
            Notification(
                receiver=recipient.person_id,
                sender=YP.organization_id,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.YQ_DISTRIBUTION,
                content=f"{YP}向您发放了本月元气值{30 + max(0, (30 - recipient.YQPoint))}点，请查收！",
            ) for recipient in recipients
        ]
        TransferRecord.objects.bulk_create(transfer_list)
        Notification.objects.bulk_create(notification_lists)
        for recipient in recipients:
            amount = 30 + max(0, (30 - recipient.YQPoint))
            recipient.YQPoint += amount
            recipient.YQPoint += recipient.YQPoint_Bonus
            recipient.YQPoint_Bonus = 0
            recipient.save()


"""
频繁执行，添加更新其他活动的定时任务，主要是为了异步调度
对于被多次落下的活动，每次更新一步状态
"""

def changeAllActivities():

    now = datetime.now()
    execute_time = now + timedelta(seconds=20)
    applying_activities = Activity.objects.filter(
        status=Activity.Status.APPLYING,
        apply_end__lte=now,
    )
    for activity in applying_activities:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}",
            run_date=execute_time, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING], replace_existing=True)
        execute_time += timedelta(seconds=5)

    waiting_activities = Activity.objects.filter(
        status=Activity.Status.WAITING,
        start__lte=now,
    )
    for activity in waiting_activities:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
            run_date=execute_time, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
        execute_time += timedelta(seconds=5)


    progressing_activities = Activity.objects.filter(
        status=Activity.Status.PROGRESSING,
        end__lte=now,
    )
    for activity in progressing_activities:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
            run_date=execute_time, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)
        execute_time += timedelta(seconds=5)


# @scheduler.scheduled_job('interval', id="get weather per hour", hours=1)
def get_weather():
    # weather = urllib.request.urlopen("http://www.weather.com.cn/data/cityinfo/101010100.html").read()
    try:
        city = "Haidian"
        key = local_dict["weather_api_key"]
        lang = "zh_cn"
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={key}&lang={lang}"
        load_json = json.loads(urllib.request.urlopen(url, timeout=5).read())  # 这里面信息太多了，不太方便传到前端
        weather_dict = {
            "modify_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "description": load_json["weather"][0]["description"],
            "temp": str(round(float(load_json["main"]["temp"]) - 273.15)),
            "temp_feel": str(round(float(load_json["main"]["feels_like"]) - 273.15)),
            "icon": load_json["weather"][0]["icon"]
        }
        with open("./weather.json", "w") as weather_json:
            json.dump(weather_dict, weather_json)
    except KeyError as e:
        log.operation_writer(SYSTEM_LOG, "天气更新异常,原因可能是local_dict中缺少weather_api_key:"+str(e), "scheduler_func[get_weather]", log.STATE_PROBLEM)
        return None
    except Exception as e:
        log.operation_writer(SYSTEM_LOG, "天气更新异常,未知错误", "scheduler_func[get_weather]", log.STATE_PROBLEM)
        return default_weather
    else:
        log.operation_writer(SYSTEM_LOG, "天气更新成功", "scheduler_func[get_weather]")
        return weather_dict


def start_scheduler(with_scheduled_job=True, debug=False):
    '''
    noexcept

    启动定时任务，先尝试添加计划任务，再启动，两部分之间互不影响
    失败时写入log
    - with_scheduled_job: 添加计划任务
    - debug: 提供具体的错误信息
    '''
    # register_job(scheduler, ...)的正确写法为scheduler.scheduled_job(...)
    # 但好像非服务器版本有问题??
    if debug: print("———————————————— Scheduler:   Debug ————————————————")
    if with_scheduled_job:
        current_job = None
        try:
            current_job = "get_weather"
            if debug: print(f"adding scheduled job '{current_job}'")
            scheduler.add_job(get_weather,
                              'interval',
                              id=current_job,
                              minutes=5,
                              replace_existing=True)
            current_job = "activityStatusUpdater"
            if debug: print(f"adding scheduled job '{current_job}'")
            scheduler.add_job(changeAllActivities,
                              "interval",
                              id=current_job,
                              minutes=5,
                              replace_existing=True)
        except Exception as e:
            info = f"add scheduled job '{current_job}' failed, reason: {e}"
            log.operation_writer(SYSTEM_LOG, info,
                            "scheduler_func[start_scheduler]", log.STATE_ERROR)
            if debug: print(info)

    try:
        if debug: print("starting schduler in scheduler_func.py")
        scheduler.start()
    except Exception as e:
        info = f"start scheduler failed, reason: {e}"
        log.operation_writer(SYSTEM_LOG, info,
                        "scheduler_func[start_scheduler]", log.STATE_ERROR)
        if debug: print(info)
        scheduler.shutdown(wait=False)
        if debug: print("successfully shutdown scheduler")
    if debug: print("———————————————— End     :   Debug ————————————————")