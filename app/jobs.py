import os
import json
import urllib.request
from typing import Dict, Any
from datetime import datetime, timedelta

from django.db import transaction  # 原子化更改数据库
from django.db.models import F

# (see: https://docs.djangoproject.com/en/dev/ref/databases/#general-notes
# for background)
# from django_apscheduler.util import close_old_connections

from boot.config import GLOBAL_CONFIG
from app.log import logger
from scheduler.adder import MultipleAdder
from scheduler.cancel import remove_job
from scheduler.periodic import periodical
from record.models import PageLog
from app.models import (
    User,
    NaturalPerson,
    OrganizationType,
    Organization,
    Activity,
    ActivityPhoto,
    Participant,
    Notification,
    Position,
    Course,
    CourseTime,
    CourseParticipant, 
)
from app.activity_utils import (
    changeActivityStatus,
    notifyActivity,
)
from app.notification_utils import (
    bulk_notification_create,
    notification_create,
)
from app.extern.wechat import WechatMessageLevel, WechatApp
from app.config import *


__all__ = [
    'send_to_persons',
    'send_to_orgs',
    'changeAllActivities',
    'get_weather',
    'get_weather_async',
    'update_active_score_per_day',
    'longterm_launch_course',
]


def send_to_persons(title, message, url='/index/'):
    # TODO: Remove hard coding
    sender = User.objects.get(username='zz00000')
    np = NaturalPerson.objects.activated().all()
    receivers = User.objects.filter(
        id__in=np.values_list('person_id', flat=True))
    print(bulk_notification_create(
        receivers, sender,
        Notification.Type.NEEDREAD, title, message, url,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT,
                     'show_source': False},
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
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT,
                     'show_source': False},
    )


@periodical('interval', job_id='activityStatusUpdater', minutes=5)
def changeAllActivities():
    """
    频繁执行，添加更新其他活动的定时任务，主要是为了异步调度
    对于被多次落下的活动，每次更新一步状态
    """
    def next_time_generator(first: timedelta | datetime, step: timedelta):
        while True:
            yield first
            first += step
    now = datetime.now()
    times = next_time_generator(now + timedelta(seconds=20), timedelta(seconds=5))
    adder = MultipleAdder(changeActivityStatus)

    def _update_all(_cur, _next, activities):
        for activity in activities:
            adder.schedule(f'activity_{activity.id}_{_next}',
                           run_time=next(times))(activity.id, _cur, _next)

    applying_activities = Activity.objects.filter(
        status=Activity.Status.APPLYING,
        apply_end__lte=now,
    )
    _update_all(Activity.Status.APPLYING, Activity.Status.WAITING, applying_activities)

    waiting_activities = Activity.objects.filter(
        status=Activity.Status.WAITING,
        start__lte=now,
    )
    _update_all(Activity.Status.WAITING, Activity.Status.PROGRESSING, waiting_activities)

    progressing_activities = Activity.objects.filter(
        status=Activity.Status.PROGRESSING,
        end__lte=now,
    )
    _update_all(Activity.Status.PROGRESSING, Activity.Status.END, progressing_activities)


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


def add_week_course_activity(course_id: int, weektime_id: int, cur_week: int, course_stage2: bool):
    """
    添加每周的课程活动
    """
    course: Course = Course.objects.get(id=course_id)
    examine_teacher = NaturalPerson.objects.get_teacher(
        CONFIG.course.audit_teacher)
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
        activity.status = Activity.Status.UNPUBLISHED
        activity.publish_day = course.publish_day
        if course.publish_day == Course.PublishDay.instant:
            # 指定为立即发布的活动在上一周结束后一天发布
            activity.publish_time = week_time.end + \
                timedelta(days=7 * cur_week - 6)
        else:
            activity.publish_time = week_time.start + \
                timedelta(days=7 * cur_week - course.publish_day)

        activity.need_apply = course.need_apply  # 是否需要报名

        if course.need_apply:
            activity.endbefore = Activity.EndBefore.onehour
            activity.apply_end = activity.start - timedelta(hours=1)

        activity.need_checkin = True  # 需要签到
        activity.recorded = True
        activity.course_time = week_time
        activity.introduction = f'{course.organization.oname}每周课程活动'
        ActivityPhoto.objects.create(image=course.photo,
                                     type=ActivityPhoto.PhotoType.ANNOUNCE,
                                     activity=activity)
        if not activity.need_apply:
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
                    status=Participant.AttendStatus.APPLYSUCCESS)

            participate_num = len(person_pos)
            activity.capacity = participate_num
            activity.current_participants = participate_num

        week_time.cur_week += 1
        week_time.save()
        activity.save()
    # 在活动发布时通知参与成员,创建定时任务并修改活动状态
    changer = MultipleAdder(changeActivityStatus)
    notifier = MultipleAdder(notifyActivity)
    # TODO: 修改UNPUBLISHED状态的诡异逻辑和状态切换
    if activity.need_apply:
        changer.schedule(f'activity_{activity.id}_{Activity.Status.APPLYING}',
            run_time=activity.publish_time
        )(activity.id, Activity.Status.UNPUBLISHED, Activity.Status.APPLYING)
        changer.schedule(f'activity_{activity.id}_{Activity.Status.WAITING}',
            run_time=activity.start - timedelta(hours=1)
        )(activity.id, Activity.Status.APPLYING, Activity.Status.WAITING)
    else:
        changer.schedule(f'activity_{activity.id}_{Activity.Status.WAITING}',
            run_time=activity.publish_time
        )(activity.id, Activity.Status.UNPUBLISHED, Activity.Status.WAITING)

    notifier.schedule(f'activity_{activity.id}_newCourseActivity',
        run_time=activity.publish_time)(activity.id, "newCourseActivity")
    notifier.schedule(f'activity_{activity.id}_remind',
        run_time=activity.start - timedelta(minutes=15))(activity.id, "remind")
    changer.schedule(f'activity_{activity.id}_{Activity.Status.PROGRESSING}',
        run_time=activity.start
    )(activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING)
    changer.schedule(f'activity_{activity.id}_{Activity.Status.END}',
        run_time=activity.end
    )(activity.id, Activity.Status.PROGRESSING, Activity.Status.END)

    notification_create(
        receiver=examine_teacher.person_id,
        sender=course.organization.get_user(),
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="新增了一个已审批的课程活动",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app": WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
    )


@periodical('interval', 'courseWeeklyActivitylauncher', minutes=5)
def longterm_launch_course():
    """
    定时发起长期课程活动
    提前一周发出课程，一般是在本周课程活动结束时发出
    本函数的循环不幂等，幂等通过课程活动创建函数的幂等实现
    """
    courses = Course.objects.activated().filter(
        status__in=[Course.Status.SELECT_END, Course.Status.STAGE2])
    for course in courses:
        for week_time in course.time_set.all():
            cur_week = week_time.cur_week
            end_week = week_time.end_week
            if cur_week < end_week:  # end_week默认16周，允许助教修改
                # 在本周课程结束后生成下一周课程活动
                due_time = week_time.end + timedelta(days=7 * cur_week)
                if due_time - timedelta(days=7) < datetime.now() < due_time:
                    # 如果处于补退选阶段：
                    course_stage2 = True if course.status == Course.Status.STAGE2 else False
                    add_week_course_activity(
                        course.id, week_time.id, cur_week, course_stage2)

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
            persons.filter(person_id__in=userids).update(
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
        
        
@periodical('cron', 'weekly_activity_summary_reminder', hour=20, minute=0, day_of_week='sun')
def weekly_activity_summary_reminder():
    '''每周日晚上8点提醒未填写周报的组织负责人，目前仅限于团委，学学学委员会，学学学学会，学生会'''
    to_notify = ['团委', '学学学委员会', '学学学学会', '学生会']
    to_notify_incharge_np_id = OrganizationType.objects.filter(
        otype_name__in=to_notify).values_list('incharge', flat=True)
    to_notify_incharge_user_id = NaturalPerson.objects.filter(
        id__in=to_notify_incharge_np_id).values_list('person_id', flat=True)
    to_notify_incharge_user = User.objects.filter(
        id__in=to_notify_incharge_user_id)
    sender = User.objects.get(username='zz00000')
    title = "每周活动总结提醒"
    message = "请于今晚12点前完成每周活动总结填报，若已完成或无可总结活动请忽略"
    bulk_notification_create(
        to_notify_incharge_user, sender,
        Notification.Type.NEEDREAD, title, message,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT,
                     'show_source': False},
    )
