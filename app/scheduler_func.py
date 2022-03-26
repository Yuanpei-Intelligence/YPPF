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
    ActivityPhoto,
    Participant,
    Notification,
    Position,
    PageLog,
    Course,
    CourseTime,
    CourseParticipant,
    Semester,
    Feedback,
)
from app.activity_utils import (
    changeActivityStatus,
    notifyActivity,
)
from app.notification_utils import (
    bulk_notification_create,
    notification_create,
    notification_status_change,
)
from app.wechat_send import publish_notifications, WechatMessageLevel, WechatApp
from app import log
from app.constants import *
from boottest import local_dict

import json
import urllib.request

from datetime import datetime, timedelta
from django.db import transaction  # 原子化更改数据库
from django.db.models import F
# (see: https://docs.djangoproject.com/en/dev/ref/databases/#general-notes 
# for background)
# from django_apscheduler.util import close_old_connections

# 引入定时任务还是放上面吧
from app.scheduler import scheduler

default_weather = get_config('default_weather', default=None)

__all__ = [
    'send_to_persons',
    'send_to_orgs',
    'distribute_YQPoint_per_month',
    'changeAllActivities',
    'get_weather',
    'update_active_score_per_day',
    'longterm_launch_course',
    'public_feedback_per_hour',
]


def send_to_persons(title, message, url='/index/'):
    sender = User.objects.get(username='zz00000')
    np = NaturalPerson.objects.activated().all()
    receivers = User.objects.filter(id__in=np.values_list('person_id', flat=True))
    print(bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT, 'show_source': False},
        ))


def send_to_orgs(title, message, url='/index/'):
    sender = User.objects.get(username='zz00000')
    org = Organization.objects.activated().all().exclude(otype__otype_id=0)
    receivers = User.objects.filter(id__in=org.values_list('organization_id', flat=True))
    bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT, 'show_source': False},
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
        log.operation_writer(SYSTEM_LOG, "天气更新异常,原因可能是local_dict中缺少weather_api_key:"+str(e), "scheduler_func[get_weather]", log.STATE_WARNING)
        return None
    except Exception as e:
        log.operation_writer(SYSTEM_LOG, "天气更新异常,未知错误", "scheduler_func[get_weather]", log.STATE_WARNING)
        return default_weather
    else:
        log.operation_writer(SYSTEM_LOG, "天气更新成功", "scheduler_func[get_weather]")
        return weather_dict


def add_week_course_activity(course_id: int, weektime_id: int, cur_week: int ,course_stage2: bool):
    """
    添加每周的课程活动
    """
    course = Course.objects.get(id=course_id)
    examine_teacher = NaturalPerson.objects.get_teacher(
        get_setting("course/audit_teacher"))
    # 当前课程在学期已举办的活动
    conducted_num = Activity.objects.activated().filter(
        organization_id=course.organization,
        category=Activity.ActivityCategory.COURSE).count()
    # 发起活动，并设置报名
    with transaction.atomic():
        week_time = CourseTime.objects.select_for_update().get(id=weektime_id)
        if week_time.cur_week != cur_week:
            return False
        start_time = week_time.start + timedelta(days=7 * cur_week)
        end_time = week_time.end + timedelta(days=7 * cur_week)
        activity = Activity.objects.create(
            title=f'{course.name}-第{conducted_num+1}次课',
            organization_id=course.organization,
            examine_teacher=examine_teacher,
            location=course.classroom,
            start=start_time,
            end=end_time,
            category=Activity.ActivityCategory.COURSE,
        )
        activity.status = Activity.Status.WAITING
        activity.need_checkin = True  # 需要签到
        activity.recorded = True
        activity.course_time = week_time
        activity.introduction = f'{course.organization.oname}每周课程活动'
        ActivityPhoto.objects.create(image=course.photo,
                                     type=ActivityPhoto.PhotoType.ANNOUNCE,
                                     activity=activity)
        # 选课人员自动报名活动
        # 选课结束以后，活动参与人员从小组成员获取
        person_pos = list(Position.objects.activated().filter(
                org=course.organization).values_list("person", flat=True))
        if course_stage2:
            # 如果处于补退选阶段，活动参与人员从课程选课情况获取
            selected_person = list(CourseParticipant.objects.filter(
                course=course,
                status=CourseParticipant.Status.SUCCESS,
            ).values_list("person", flat=True))
            person_pos += selected_person
            person_pos = list(set(person_pos))
        members = NaturalPerson.objects.filter(
            id__in=person_pos)
        for member in members:
            participant = Participant.objects.create(
                activity_id=activity,
                person_id=member,
                status=Participant.AttendStatus.APLLYSUCCESS)

        participate_num = len(person_pos)
        activity.capacity = participate_num
        activity.current_participants = participate_num
        week_time.cur_week += 1
        week_time.save()
        activity.save()

    # 通知参与成员,创建定时任务并修改活动状态
    notifyActivity(activity.id, "newCourseActivity")

    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
                      run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
                      run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
                      run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)

    notification_create(
        receiver=examine_teacher.person_id,
        sender=course.organization.organization_id,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="新增了一个已审批的课程活动",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app": WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
    )


def longterm_launch_course():
    """
    定时发起长期课程活动
    提前一周发出课程，一般是在本周课程活动结束时发出
    本函数的循环不幂等，幂等通过课程活动创建函数的幂等实现
    """
    courses = Course.objects.activated().filter(status__in=[Course.Status.SELECT_END,Course.Status.STAGE2])
    for course in courses:
        for week_time in course.time_set.all():
            cur_week = week_time.cur_week
            end_week = week_time.end_week
            if cur_week < end_week:  #   end_week默认16周，允许助教修改
                #提前6天发布
                due_time = week_time.end + timedelta(days=7 * cur_week)
                if due_time - timedelta(days=6) < datetime.now() < due_time:
                    # 如果处于补退选阶段：
                    course_stage2 = True if course.status == Course.Status.STAGE2 else False
                    add_week_course_activity(course.id, week_time.id, cur_week, course_stage2)


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
            persons.filter(person_id__in=userids).update(
                active_score=F('active_score') + 1 / days)


def public_feedback_per_hour():
    '''查找距离组织公开反馈24h内没被审核的反馈，将其公开'''
    time = datetime.now() - timedelta(days=1)
    with transaction.atomic():
        feedbacks = Feedback.objects.filter(
            issue_status=Feedback.IssueStatus.ISSUED,
            public_status=Feedback.PublicStatus.PRIVATE,
            publisher_public=True,
            org_public=True,
            public_time__lte=time,
        )
        feedbacks.select_for_update().update(
            public_status=Feedback.PublicStatus.PUBLIC)
        for feedback in feedbacks:
            notification_create(
                receiver=feedback.person.person_id,
                sender=feedback.org.otype.incharge.person_id,
                typename=Notification.Type.NEEDREAD,
                title="反馈状态更新",
                content=f"您的反馈[{feedback.title}]已被公开",
                URL=f"/viewFeedback/{feedback.id}",
                anonymous_flag=False,
                publish_to_wechat=True,
                publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
            )
            notification_create(
                receiver=feedback.org.organization_id,
                sender=feedback.org.otype.incharge.person_id,
                typename=Notification.Type.NEEDREAD,
                title="反馈状态更新",
                content=f"您处理的反馈[{feedback.title}]已被公开",
                URL=f"/viewFeedback/{feedback.id}",
                anonymous_flag=False,
                publish_to_wechat=True,
                publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
            )


def cancel_related_jobs(instance, extra_ids=None):
    '''删除关联的定时任务（可以在模型中预定义related_job_ids）'''
    if hasattr(instance, 'related_job_ids'):
        job_ids = instance.related_job_ids
        if callable(job_ids):
            job_ids = job_ids()
        for job_id in job_ids:
            try: scheduler.remove_job(job_id)
            except: continue
    if extra_ids is not None:
        for job_id in extra_ids:
            try: scheduler.remove_job(job_id)
            except: continue

def _cancel_jobs(sender, instance, **kwargs):
    cancel_related_jobs(instance)

def register_pre_delete():
    '''注册删除前清除定时任务的函数'''
    import app.models
    from django.db import models
    for name in app.models.__all__:
        try:
            model = getattr(app.models, name)
            assert issubclass(model, models.Model)
            assert hasattr(model, 'related_job_ids')
        except:
            # 不具有关联任务的模型无需设置
            continue
        models.signals.pre_delete.connect(_cancel_jobs, sender=model)
