import json
import os
import urllib.request
from datetime import datetime, timedelta, date
from typing import Any, Dict

from django.db import transaction  # 原子化更改数据库
from django.db.models import F

from utils.marker import script
import utils.models.query as SQ
from boot.config import GLOBAL_CONFIG
from semester.api import current_semester
from record.models import PageLog
from scheduler.adder import MultipleAdder
from scheduler.cancel import remove_job
from scheduler.periodic import periodical
from app.models import (
    User,
    NaturalPerson,
    Organization,
    OrganizationType,
    Notification,
    Position,
)
from app.notification_utils import (
    bulk_notification_create,
    notification_create,
)
from app.extern.wechat import WechatApp, WechatMessageLevel
from app.log import logger
from app.config import *


__all__ = [
    'send_to_persons',
    'send_to_orgs',
    'changeAllActivities',
    'get_weather',
    'get_weather_async',
    'update_active_score_per_day',
    'longterm_launch_course',
    'happy_birthday',
    'weekly_activity_summary_reminder',
]


def send_to_persons(title, message, url='/index/'):
    # TODO: Remove hard coding
    sender = User.objects.get(username='zz00000')
    np = NaturalPerson.objects.activated().all()
    receivers = User.objects.filter(
        id__in=SQ.qsvlist(np, NaturalPerson.person_id))
    print(bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        to_wechat=dict(level=WechatMessageLevel.IMPORTANT, show_source=False),
    ))


def send_to_orgs(title, message, url='/index/'):
    # TODO: Remove hard coding
    sender = User.objects.get(username='zz00000')
    org = Organization.objects.activated().all().exclude(otype__otype_id=0)
    receivers = User.objects.filter(
        id__in=org.values_list('organization_id', flat=True))
    bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        to_wechat=dict(level=WechatMessageLevel.IMPORTANT, show_source=False),
    )


@periodical('interval', job_id="get weather per hour", hours=1)
def get_weather_async():
    city = "Haidian"
    key = CONFIG.weather_api_key
    lang = "zh_cn"
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={key}&lang={lang}"
    try:
        load_json = json.loads(urllib.request.urlopen(url, timeout=5).read())
        weather_dict = {
            "modify_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "description": load_json["weather"][0]["description"],
            "temp": str(round(float(load_json["main"]["temp"]) - 273.15)),
            "temp_feel": str(round(float(load_json["main"]["feels_like"]) - 273.15)),
            "icon": load_json["weather"][0]["icon"]
        }
        os.makedirs(GLOBAL_CONFIG.temporary_dir, exist_ok=True)
        with open(os.path.join(GLOBAL_CONFIG.temporary_dir, "weather.json"), "w") as f:
            json.dump(weather_dict, f)
    except:
        logger.exception('天气更新异常')


def get_weather() -> Dict[str, Any]:
    weather_file = os.path.join(GLOBAL_CONFIG.temporary_dir, "weather.json")
    if not os.path.exists(weather_file):
        return dict()
    with open(weather_file, "r") as f:
        return json.load(f)



@periodical('cron', 'active_score_updater', hour=1)
def update_active_score_per_day(days=14):
    '''每天计算用户活跃度， 计算前days天（不含今天）内的平均活跃度'''
    with transaction.atomic():
        today = datetime.now().date()
        persons = NaturalPerson.objects.activated().select_for_update()
        persons.update(active_score=0)
        for i in range(days):
            date = today - timedelta(days=i+1)
            userids = set(PageLog.objects.filter(
                time__date=date).values_list('user', flat=True))
            persons.filter(SQ.mq(NaturalPerson.person_id, IN=userids)).update(
                active_score=F('active_score') + 1 / days)


# TODO: Move these to schedueler app
def cancel_related_jobs(instance, extra_ids=None):
    '''删除关联的定时任务（可以在模型中预定义related_job_ids）'''
    if hasattr(instance, 'related_job_ids'):
        job_ids = instance.related_job_ids
        if callable(job_ids):
            job_ids = job_ids()
        for job_id in job_ids:
            remove_job(job_id)
    if extra_ids is not None:
        for job_id in extra_ids:
            remove_job(job_id)


def _cancel_jobs(sender, instance, **kwargs):
    cancel_related_jobs(instance)


def register_pre_delete():
    '''注册删除前清除定时任务的函数'''
    from django.db import models

    import app.models
    for name in app.models.__all__:
        try:
            model = getattr(app.models, name)
            assert issubclass(model, models.Model)
            assert hasattr(model, 'related_job_ids')
        except:
            # 不具有关联任务的模型无需设置
            continue
        models.signals.pre_delete.connect(_cancel_jobs, sender=model)


@script
@periodical('cron', 'happy_birthday', hour=6)
def happy_birthday():
    # get person
    from django.db.models import QuerySet
    month, day = date.today().month, date.today().day
    np: QuerySet[NaturalPerson] = NaturalPerson.objects.activated().filter(
        birthday__month=month, birthday__day=day
    )
    stus = np.filter(identity=NaturalPerson.Identity.STUDENT)
    teachers = np.filter(identity=NaturalPerson.Identity.TEACHER)
    # prepare send
    crowds = [stus, teachers]
    messages = [
        "愿少年不惧岁月长，新的一岁光彩依旧，兴致盎然~",
        "旦逢良辰，顺颂时宜。愿君常似少年时，永远二十赶朝暮~",
    ]
    title = "元培学院祝你生日快乐！"
    url = None
    sender = User.objects.get(username='zz00000')
    for np, message in zip(crowds, messages):
        receivers = User.objects.filter(
            id__in=SQ.qsvlist(np, NaturalPerson.person_id))
        bulk_notification_create(
            receivers, sender,
            Notification.Type.NEEDREAD, title, message, url,
            to_wechat=dict(level=WechatMessageLevel.IMPORTANT, show_source=False),
        )
