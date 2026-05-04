"""
activity_utils.py

这个文件应该只被 ./activity_views.py, ./scheduler_func.py 依赖
依赖于 ./utils.py, ./wechat_send.py, ./notification_utils.py

scheduler_func 依赖于 wechat_send 依赖于 utils

文件中参数存在 activity 的函数需要在 transaction.atomic() 块中进行。
如果存在预期异常，抛出 ActivityException，否则抛出其他异常
"""
import io
import base64
import random
from typing import Iterable
from datetime import datetime, timedelta

import qrcode

from utils.http.utils import build_full_url
import utils.models.query as SQ
from generic.models import User, YQPointRecord
from scheduler.adder import ScheduleAdder
from scheduler.cancel import remove_job
from app.utils_dependency import *
from app.models import (
    User,
    NaturalPerson as Person,
    Organization,
    Organization as Org,
    OrganizationType as OrgType,
    Position,
    Activity,
    Participation,
    Notification,
    ActivityPhoto,
)
from app.utils import get_person_or_org, if_image
from app.notification_utils import (
    notification_create,
    bulk_notification_create,
    notification_status_change,
)
from app.extern.wechat import WechatApp, WechatMessageLevel
from app.log import logger


__all__ = [
    'changeActivityStatus',
    'notifyActivity',
    'ActivityException',
    'create_activity',
    'modify_activity',
    'accept_activity',
    'reject_activity',
    'apply_activity',
    'cancel_activity',
    'withdraw_activity',
    'get_activity_QRcode',
    'create_participate_infos',
    'modify_participants',
    'weekly_summary_orgs',
    'available_participants',
]


"""
使用方式：
scheduler.add_job(changeActivityStatus, "date",
    id=f"activity_{aid}_{to_status}", run_date, args)
注意：
    1、当 cur_status 不为 None 时，检查活动是否为给定状态
    2、一个活动每一个目标状态最多保留一个定时任务
允许的状态变换：
    2、报名中 -> 等待中
    3、等待中 -> 进行中
    4、进行中 -> 已结束
活动变更为进行中时，更新报名成功人员状态
"""


@logger.secure_func('活动状态更新异常')
@logger.secure_func('检查活动状态', exc_type=AssertionError)
@transaction.atomic
def changeActivityStatus(aid, cur_status, to_status):
    '''
    幂等；可能发生异常；包装器负责处理异常
    必须提供cur_status，则会在转换状态前检查前后状态，每次只能变更一个阶段
    即：报名中->等待中->进行中->结束
    状态不符合时，抛出AssertionError
    '''
    activity = Activity.objects.select_for_update().get(id=aid)
    if cur_status is None:
        raise AssertionError('未提供当前状态，不允许进行活动状态修改')
    if activity.status == Activity.Status.CANCELED:
        return
    assert cur_status == activity.status, f'<{activity.status}>与期望的状态<{cur_status}>不符'

    FSM = [
        (Activity.Status.APPLYING, Activity.Status.WAITING),
        (Activity.Status.WAITING, Activity.Status.PROGRESSING),
        (Activity.Status.PROGRESSING, Activity.Status.END),
    ]
    LIMITED_STATUS = list(set(map(lambda x: x[0], FSM)))
    if cur_status in LIMITED_STATUS:
        assert (cur_status, to_status) in FSM, f'不能从{cur_status}变更到{to_status}'

    if to_status == Activity.Status.WAITING:
        if activity.bidding:
            draw_lots(activity)

    # 活动变更为进行中时，修改参与人参与状态
    elif to_status == Activity.Status.PROGRESSING:
        unchecked = SQ.sfilter(Participation.activity, activity).filter(
            status=Participation.AttendStatus.APPLYSUCCESS)
        if activity.need_checkin:
            unchecked.update(status=Participation.AttendStatus.UNATTENDED)
        else:
            unchecked.update(status=Participation.AttendStatus.ATTENDED)

        # if not activity.valid:
        #     # 活动开始后，未审核自动通过
        #     activity.valid = True
        #     notification = Notification.objects.get(
        #         relate_instance=activity,
        #         status=Notification.Status.UNDONE,
        #         title=Notification.Title.VERIFY_INFORM
        #     )
        #     notification_status_change(notification, Notification.Status.DONE)

    # 结束，计算元气值
    elif (to_status == Activity.Status.END
            and activity.category != Activity.ActivityCategory.COURSE):
        activity.settle_yqpoint(status=to_status)
    # 过早进行这个修改，将被写到activity待执行的保存中，导致失败后调用activity.save仍会调整状态
    activity.status = to_status
    activity.save()


"""
需要在 transaction 中使用
所有涉及到 activity 的函数，都应该先锁 activity
"""


def draw_lots(activity: Activity):
    participation = SQ.sfilter(Participation.activity, activity)
    participation: QuerySet[Participation]
    l = len(participation.filter(status=Participation.AttendStatus.APPLYING))

    engaged = len(participation.filter(
        status__in=[Participation.AttendStatus.APPLYSUCCESS,
                    Participation.AttendStatus.UNATTENDED,
                    Participation.AttendStatus.ATTENDED]
    ))

    leftQuota = activity.capacity - engaged

    if l <= leftQuota:
        participation.filter(
            status__in=[Participation.AttendStatus.APPLYING,
                        Participation.AttendStatus.APPLYFAILED]
        ).update(status=Participation.AttendStatus.APPLYSUCCESS)
        activity.current_participants = engaged + l
    else:
        lucky_ones = random.sample(range(l), leftQuota)
        activity.current_participants = activity.capacity
        for i, participant in enumerate(participation.select_for_update().filter(
                status__in=[Participation.AttendStatus.APPLYING,
                            Participation.AttendStatus.APPLYFAILED]
        )):
            if i in lucky_ones:
                participant.status = Participation.AttendStatus.APPLYSUCCESS
            else:
                participant.status = Participation.AttendStatus.APPLYFAILED
            participant.save()
    # 签到成功的转发通知和微信通知
    receivers = SQ.qsvlist(participation.filter(
        status=Participation.AttendStatus.APPLYSUCCESS
    ), Participation.person, Person.person_id)
    receivers = User.objects.filter(id__in=receivers)
    sender = activity.organization_id.get_user()
    typename = Notification.Type.NEEDREAD
    content = f'您好！您参与抽签的活动“{activity.title}”报名成功！请准时参加活动！'
    URL = f'/viewActivity/{activity.id}'
    if len(receivers) > 0:
        bulk_notification_create(
            receivers=receivers,
            sender=sender,
            typename=typename,
            title=Notification.Title.ACTIVITY_INFORM,
            content=content,
            URL=URL,
            to_wechat=dict(app=WechatApp.TO_PARTICIPANT, level=WechatMessageLevel.IMPORTANT),
        )
    # 抽签失败的同学发送通知
    receivers = SQ.qsvlist(participation.filter(
        status=Participation.AttendStatus.APPLYFAILED
    ), Participation.person, Person.person_id)
    receivers = User.objects.filter(id__in=receivers)
    content = f'很抱歉通知您，您参与抽签的活动“{activity.title}”报名失败！'
    if len(receivers) > 0:
        bulk_notification_create(
            receivers=receivers,
            sender=sender,
            typename=typename,
            title=Notification.Title.ACTIVITY_INFORM,
            content=content,
            URL=URL,
            to_wechat=dict(app=WechatApp.TO_PARTICIPANT, level=WechatMessageLevel.IMPORTANT),
        )


"""
使用方式：
scheduler.add_job(notifyActivityStart, "date",
    id=f"activity_{aid}_{start_notification}", run_date, args)
"""


def _participant_uids(activity: Activity) -> list[int]:
    participant_person_id = SQ.qsvlist(Participation.objects.filter(
        SQ.sq(Participation.activity, activity),
        SQ.mq(Participation.status, IN=[Participation.AttendStatus.APPLYSUCCESS,
                                      Participation.AttendStatus.APPLYING])
    ), Participation.person)
    return SQ.qsvlist(Person.objects.activated().filter(
        id__in=participant_person_id), Person.person_id)


def _subscriber_uids(activity: Activity) -> list[int]:
    return SQ.qsvlist(Person.objects.activated().exclude(
        id__in=activity.organization_id.unsubscribers.all()
    ), Person.person_id)


@logger.secure_func('活动消息发送异常')
def notifyActivity(aid: int, msg_type: str, msg=""):
    activity = Activity.objects.get(id=aid)
    inner = activity.inner
    title = Notification.Title.ACTIVITY_INFORM
    if msg_type == "newActivity":
        title = activity.title
        msg = f"您关注的小组{activity.organization_id.oname}发布了新的活动。"
        msg += f"\n开始时间: {activity.start.strftime('%Y-%m-%d %H:%M')}"
        msg += f"\n活动地点: {activity.location}"
        receivers = User.objects.filter(id__in=_subscriber_uids(activity))
        publish_kws = dict(app=WechatApp.TO_SUBSCRIBER)
    elif msg_type == "remind":
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)
            nowtime = datetime.now()
            notifications = Notification.objects.filter(
                relate_instance=activity,
                start_time__gt=nowtime + timedelta(seconds=60),
                title=Notification.Title.PENDING_INFORM,
            )
            if len(notifications) > 0:
                return
            msg = f"您参与的活动 <{activity.title}> 即将开始。"
            msg += f"\n开始时间: {activity.start.strftime('%Y-%m-%d %H:%M')}"
            msg += f"\n活动地点: {activity.location}"
            receivers = User.objects.filter(id__in=_participant_uids(activity))
            publish_kws = dict(app=WechatApp.TO_PARTICIPANT)

    elif msg_type == 'modification_sub':
        receivers = User.objects.filter(id__in=_subscriber_uids(activity))
        publish_kws = dict(app=WechatApp.TO_SUBSCRIBER)
    elif msg_type == 'modification_par':
        receivers = User.objects.filter(id__in=_participant_uids(activity))
        publish_kws = dict(
            app=WechatApp.TO_PARTICIPANT,
            level=WechatMessageLevel.IMPORTANT,
        )
    elif msg_type == "modification_sub_ex_par":
        receiver_uids = list(set(_subscriber_uids(activity)) -
                             set(_participant_uids(activity)))
        receivers = User.objects.filter(id__in=receiver_uids)
        publish_kws = dict(app=WechatApp.TO_SUBSCRIBER)

    # 应该用不到了，调用的时候分别发给 par 和 sub
    # 主要发给两类用户的信息往往是不一样的
    elif msg_type == 'modification_all':
        receiver_uids = list(set(_subscriber_uids(activity)) |
                             set(_participant_uids(activity)))
        receivers = User.objects.filter(id__in=receiver_uids)
        publish_kws = dict(app=WechatApp.TO_SUBSCRIBER)
    elif msg_type == 'newCourseActivity':
        title = activity.title
        msg = f"课程{activity.organization_id.oname}发布了新的课程活动。"
        msg += f"\n开始时间: {activity.start.strftime('%Y-%m-%d %H:%M')}"
        msg += f"\n活动地点: {activity.location}"
        receiver_uids = list(set(_subscriber_uids(activity)) |
                             set(_participant_uids(activity)))
        receivers = User.objects.filter(id__in=receiver_uids)
        publish_kws = dict(app=WechatApp.TO_SUBSCRIBER)
    else:
        raise ValueError(f"msg_type参数错误: {msg_type}")

    if inner and publish_kws.get('app') == WechatApp.TO_SUBSCRIBER:
        member_id_list = SQ.qsvlist(Position.objects.activated().filter(
            org=activity.organization_id), Position.person, Person.person_id)
        receivers = receivers.filter(id__in=member_id_list)

    success, _ = bulk_notification_create(
        receivers=list(receivers),
        sender=activity.organization_id.get_user(),
        typename=Notification.Type.NEEDREAD,
        title=title,
        content=msg,
        URL=f"/viewActivity/{aid}",
        relate_instance=activity,
        to_wechat=publish_kws,
    )
    assert success, "批量创建通知并发送时失败"


def get_activity_QRcode(activity):
    auth_code = GLOBAL_CONFIG.hasher.encode(str(activity.id))
    url = build_full_url(f'checkinActivity/{activity.id}?auth={auth_code}')
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=5,
        border=5,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    io_buffer = io.BytesIO()
    img.save(io_buffer, "png")
    data = base64.encodebytes(io_buffer.getvalue()).decode()
    return "data:image/png;base64," + str(data)


class ActivityException(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


# 时间合法性的检查，检查时间是否在当前时间的一个月以内，并且检查开始的时间是否早于结束的时间，
def check_ac_time(start_time: datetime, end_time: datetime) -> bool:
    now_time = datetime.now()
    month_late = now_time + timedelta(days=30)
    if not start_time < end_time:
        return False
    if now_time < start_time < month_late:
        return True  # 时间所处范围正确

    return False


def activity_base_check(request, edit=False):
    '''正常情况下检查出错误会抛出不含错误信息的AssertionError，不抛出ActivityException'''

    context = dict()

    # title, introduction, location 创建时不能为空
    context["title"] = request.POST["title"]
    context["introduction"] = request.POST["introduction"]
    context["location"] = request.POST["location"]
    assert len(context["title"]) > 0
    assert len(context["introduction"]) > 0
    assert len(context["location"]) > 0

    # url，就不支持了 http 了，真的没必要
    context["url"] = request.POST["URL"]
    if context["url"] != "":
        assert context["url"].startswith(
            "http://") or context["url"].startswith("https://")

    # 在审核通过后，这些不可修改
    signscheme = int(request.POST["signscheme"])
    if signscheme:
        context["bidding"] = True
    else:
        context["bidding"] = False

    # examine_teacher 需要特殊检查
    context["examine_teacher"] = request.POST.get("examine_teacher")

    # 预报备
    context["recorded"] = False
    if request.POST.get("recorded"):
        context["recorded"] = True

    # 时间
    act_start = datetime.strptime(
        request.POST["actstart"], "%Y-%m-%d %H:%M")  # 活动报名时间
    act_end = datetime.strptime(
        request.POST["actend"], "%Y-%m-%d %H:%M")  # 活动报名结束时间
    context["start"] = act_start
    context["end"] = act_end
    assert check_ac_time(act_start, act_end)

    # create 或者调整报名时间，都是要确保活动不要立刻截止报名
    now_time = datetime.now()
    if not edit or request.POST.get("adjust_apply_ddl"):
        prepare_scheme = int(request.POST["prepare_scheme"])
        prepare_times = Activity.EndBeforeHours.prepare_times
        prepare_time = prepare_times[prepare_scheme]
        signup_end = act_start - timedelta(hours=prepare_time)
        assert now_time <= signup_end
        context["endbefore"] = prepare_scheme
        context["signup_end"] = signup_end
    else:
        # 修改但不调整报名截止时间，后面函数自己查
        context["adjust_apply"] = False

    # 人数限制
    capacity = request.POST.get("maxpeople")
    no_limit = request.POST.get("unlimited_capacity")
    if no_limit is not None:
        capacity = 10000
    if capacity is not None and capacity != "":
        capacity = int(capacity)
        assert capacity >= 0
    context["capacity"] = capacity

    # 需要签到
    if request.POST.get("need_checkin"):
        context["need_checkin"] = True

    # 内部活动
    if request.POST.get("inner"):
        context["inner"] = True
    else:
        context["inner"] = False

    # 图片 优先使用上传的图片
    announcephoto = request.FILES.getlist("images")
    if len(announcephoto) > 0:
        pic = announcephoto[0]
        assert if_image(pic) == 2
    else:
        if request.POST.get("picture1"):
            pic = request.POST.get("picture1")
        elif request.POST.get("picture2"):
            pic = request.POST.get("picture2")
        elif request.POST.get("picture3"):
            pic = request.POST.get("picture3")
        elif request.POST.get("picture4"):
            pic = request.POST.get("picture4")
        else:
            pic = request.POST.get("picture5")

    if pic is None:
        template_id = request.POST.get("template_id")
        if template_id:
            context["template_id"] = int(template_id)
        else:
            assert edit
    else:
        context["pic"] = pic

    return context


def _set_change_status(activity: Activity, current, next, time, replace):
    ScheduleAdder(changeActivityStatus, id=f'activity_{activity.id}_{next}',
                  run_time=time, replace=replace)(activity.id, current, next)


def _set_jobs_to_status(activity: Activity, replace: bool) -> Activity.Status:
    now_time = datetime.now()
    status = Activity.Status.END
    if now_time < activity.end:
        status, next = Activity.Status.PROGRESSING, Activity.Status.END
        _set_change_status(activity, status, next, activity.end, replace)
    if now_time < activity.start:
        status, next = Activity.Status.WAITING, Activity.Status.PROGRESSING
        _set_change_status(activity, status, next, activity.start, replace)
    if now_time < activity.apply_end:
        status, next = Activity.Status.APPLYING, Activity.Status.WAITING
        _set_change_status(activity, status, next, activity.apply_end, replace)
    if now_time < activity.start - timedelta(minutes=15):
        reminder = ScheduleAdder(notifyActivity, id=f'activity_{activity.id}_remind',
                                 run_time=activity.start - timedelta(minutes=15), replace=replace)
        reminder(activity.id, 'remind')
    return status


def create_activity(request):
    '''
    检查活动，合法时寻找该活动，不存在时创建
    返回(activity.id, created)

    ---
    检查不合格时抛出AssertionError
    - 不再假设ActivityException特定语义，暂不抛出该类异常
    '''

    context = activity_base_check(request)

    # 查找是否有类似活动存在
    old_ones = Activity.objects.activated().filter(
        title=context["title"],
        start=context["start"],
        introduction=context["introduction"],
        location=context["location"]
    )
    if len(old_ones) == 0:
        old_ones = Activity.objects.filter(
            title=context["title"],
            start=context["start"],
            introduction=context["introduction"],
            location=context["location"],
            status=Activity.Status.REVIEWING,
        )
    if len(old_ones):
        assert len(old_ones) == 1, "创建活动时，已存在的相似活动不唯一"
        return old_ones[0].id, False

    # 审批老师存在
    examine_teacher = Person.objects.get_teacher(context["examine_teacher"])

    # 检查完毕，创建活动
    org = get_person_or_org(request.user, UTYPE_ORG)
    activity = Activity.objects.create(
        title=context["title"],
        organization_id=org,
        examine_teacher=examine_teacher,
        introduction=context["introduction"],
        location=context["location"],
        capacity=context["capacity"],
        URL=context["url"],
        start=context["start"],
        end=context["end"],
        bidding=context["bidding"],
        apply_end=context["signup_end"],
        inner=context["inner"],
    )
    activity.endbefore = context["endbefore"]
    if context.get("need_checkin"):
        activity.need_checkin = True
    if context["recorded"]:
        # 预报备活动，先开放报名，再审批
        activity.recorded = True
        activity.status = Activity.Status.APPLYING
        notifyActivity(activity.id, "newActivity")
        _set_jobs_to_status(activity, replace=False)

    activity.save()

    if context.get("template_id"):
        template = Activity.objects.get(id=context["template_id"])
        photo = ActivityPhoto.objects.get(
            type=ActivityPhoto.PhotoType.ANNOUNCE, activity=template)
        photo.pk = None
        photo.id = None
        photo.activity = activity
        photo.save()
    else:
        ActivityPhoto.objects.create(
            image=context["pic"], type=ActivityPhoto.PhotoType.ANNOUNCE, activity=activity)

    notification_create(
        receiver=examine_teacher.person_id,
        sender=request.user,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="您有一个活动待审批",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        to_wechat=dict(app=WechatApp.AUDIT),
    )

    return activity.id, True


def modify_activity(request, activity):

    if activity.status == Activity.Status.REVIEWING:
        modify_reviewing_activity(request, activity)
    elif activity.status == Activity.Status.APPLYING or activity.status == Activity.Status.WAITING:
        modify_accepted_activity(request, activity)
    else:
        raise ValueError


"""
检查 修改审核中活动 的 request
审核中，只需要修改内容，不需要通知
但如果修改了审核老师，需要再通知新的审核老师，并 close 原审核请求
"""


def modify_reviewing_activity(request, activity):

    context = activity_base_check(request, edit=True)

    if context.get("adjust_apply") is not None:
        # 注意这里是不调整
        assert context["adjust_apply"] == False
        assert activity.apply_end <= context["start"] - timedelta(hours=1)
    else:
        activity.apply_end = context["signup_end"]
        activity.endbefore = context["endbefore"]

    activity.title = context["title"]
    activity.introduction = context["introduction"]
    activity.location = context["location"]
    activity.capacity = context["capacity"]
    activity.URL = context["url"]
    activity.start = context["start"]
    activity.end = context["end"]
    activity.bidding = context["bidding"]
    if context.get("need_checkin"):
        activity.need_checkin = True
    else:
        activity.need_checkin = False
    if context.get("inner"):
        activity.inner = True
    else:
        activity.inner = False
    activity.save()

    # 图片
    if context.get("pic") is not None:
        pic = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
        pic.image = context["pic"]
        pic.save()


"""
对已经通过审核的活动进行修改
不能修改预算，元气值支付模式，审批老师
只能修改时间，地点，URL, 简介，向同学收取元气值时的元气值数量

# 这个实际上应该是 activated/valid activity
"""


def modify_accepted_activity(request, activity):

    # TODO 删除任务，注册新任务

    to_participants = [f"您参与的活动{activity.title}发生变化"]
    # to_subscribers = [f"您关注的活动{activity.title}发生变化"]
    if activity.location != request.POST["location"]:
        to_participants.append("活动地点修改为" + request.POST["location"])
        activity.location = request.POST["location"]

    # 时间改变
    act_start = datetime.strptime(request.POST["actstart"], "%Y-%m-%d %H:%M")
    now_time = datetime.now()
    assert now_time < act_start

    if request.POST.get("adjust_apply_ddl"):
        prepare_scheme = int(request.POST["prepare_scheme"])
        prepare_times = Activity.EndBeforeHours.prepare_times
        prepare_time = prepare_times[prepare_scheme]
        signup_end = act_start - timedelta(hours=prepare_time)
        assert now_time <= signup_end
        activity.apply_end = signup_end
        activity.endbefore = prepare_scheme
        # to_subscribers.append(f"活动报名截止时间调整为{signup_end.strftime('%Y-%m-%d %H:%M')}")
        to_participants.append(
            f"活动报名截止时间调整为{signup_end.strftime('%Y-%m-%d %H:%M')}")
    else:
        signup_end = activity.apply_end
        assert signup_end + timedelta(hours=1) <= act_start

    if activity.start != act_start:
        # to_subscribers.append(f"活动开始时间调整为{act_start.strftime('%Y-%m-%d %H:%M')}")
        to_participants.append(
            f"活动开始时间调整为{act_start.strftime('%Y-%m-%d %H:%M')}")
        activity.start = act_start

    if signup_end < now_time and activity.status == Activity.Status.WAITING:
        activity.status = Activity.Status.APPLYING

    if request.POST.get("unlimited_capacity"):
        capacity = 10000
    else:
        capacity = int(request.POST["maxpeople"])
        assert capacity > 0
        if capacity < len(SQ.sfilter(Participation.activity, activity).filter(
            status=Participation.AttendStatus.APPLYSUCCESS
        )):
            raise ActivityException(f"当前成功报名人数已超过{capacity}人!")
    activity.capacity = capacity

    if request.POST.get("need_checkin"):
        activity.need_checkin = True
    else:
        activity.need_checkin = False

    # 内部活动
    if request.POST.get("inner"):
        activity.inner = True
    else:
        activity.inner = False

    activity.end = datetime.strptime(request.POST["actend"], "%Y-%m-%d %H:%M")
    assert activity.start < activity.end
    activity.URL = request.POST["URL"]
    activity.introduction = request.POST["introduction"]
    activity.save()

    _set_jobs_to_status(activity, replace=True)

    # if len(to_subscribers) > 1:
    #     notifyActivity(activity.id, "modification_sub_ex_par", "\n".join(to_subscribers))
    if len(to_participants) > 1:
        notifyActivity(activity.id, "modification_par",
                       "\n".join(to_participants))


def accept_activity(request, activity):

    # 审批通过
    activity.valid = True

    # 通知
    notification = Notification.objects.get(
        relate_instance=activity,
        status=Notification.Status.UNDONE,
        title=Notification.Title.VERIFY_INFORM
    )
    notification_status_change(notification, Notification.Status.DONE)

    notification_create(
        receiver=activity.organization_id.get_user(),
        sender=request.user,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACTIVITY_INFORM,
        content=f"您的活动{activity.title}已通过审批。",
        URL=f"/viewActivity/{activity.id}",
        relate_instance=activity,
        to_wechat=dict(app=WechatApp.AUDIT),
    )

    if activity.status == Activity.Status.REVIEWING:
        activity.status = _set_jobs_to_status(activity, replace=False)

    activity.save()


def _remove_jobs(activity: Activity, *jobs):
    for job in jobs:
        remove_job(f"activity_{activity.id}_{job}")


def _remove_activity_jobs(activity: Activity):
    _remove_jobs(activity, 'remind', Activity.Status.WAITING,
                 Activity.Status.PROGRESSING, Activity.Status.END)


def reject_activity(request, activity):
    # 审批过，这个叫 valid 不太合适......
    activity.valid = True

    # 通知
    notification = Notification.objects.get(
        relate_instance=activity,
        status=Notification.Status.UNDONE,
        title=Notification.Title.VERIFY_INFORM
    )
    notification_status_change(notification, Notification.Status.DONE)

    if activity.status == Activity.Status.REVIEWING:
        activity.status = Activity.Status.REJECT
    else:
        Notification.objects.filter(
            relate_instance=activity
        ).update(status=Notification.Status.DELETE)
        # 曾将所有报名的人的状态改为申请失败
        notifyActivity(activity.id, "modification_par",
                       f"您报名的活动{activity.title}已取消。")
        activity.status = Activity.Status.CANCELED
        _remove_activity_jobs(activity)

    notification = notification_create(
        receiver=activity.organization_id.get_user(),
        sender=request.user,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACTIVITY_INFORM,
        content=f"您的活动{activity.title}被拒绝。",
        URL=f"/viewActivity/{activity.id}",
        relate_instance=activity,
        to_wechat=dict(app=WechatApp.AUDIT),
    )

    activity.save()


# 调用的时候用 try
def apply_activity(request, activity: Activity):
    '''这个函数在正常情况下只应该抛出提示错误信息的ActivityException'''
    context = dict()
    context["success"] = False

    payer = Person.objects.get_by_user(request.user)

    if activity.inner:
        position = Position.objects.activated().filter(
            person=payer, org=activity.organization_id)
        if len(position) == 0:
            # 按理说这里也是走不到的，前端会限制
            raise ActivityException(
                f"该活动是{activity.organization_id}内部活动，暂不开放对外报名。")

    try:
        participant = Participation.objects.select_for_update().get(
            SQ.sq(Participation.activity, activity),
            SQ.sq(Participation.person, payer),
        )
        participated = True
    except:
        participated = False
    if participated:
        if (
            participant.status == Participation.AttendStatus.APPLYSUCCESS or
            participant.status == Participation.AttendStatus.APPLYING
        ):
            raise ActivityException("您已报名该活动。")
        elif participant.status != Participation.AttendStatus.CANCELED:
            raise ActivityException(f"您的报名状态异常，当前状态为：{participant.status}")

    if not activity.bidding:
        if activity.current_participants < activity.capacity:
            activity.current_participants += 1
        else:
            raise ActivityException("活动已报满，请稍后再试。")
    else:
        activity.current_participants += 1

    if not participated:
        participant = Participation.objects.create(**dict([
            (SQ.f(Participation.activity), activity),
            (SQ.f(Participation.person), payer),
        ]))
    if not activity.bidding:
        participant.status = Participation.AttendStatus.APPLYSUCCESS
    else:
        participant.status = Participation.AttendStatus.APPLYING

    participant.save()
    activity.save()


def cancel_activity(request, activity):

    if activity.status == Activity.Status.REVIEWING:
        activity.status = Activity.Status.ABORT
        activity.save()
        # 修改老师的通知
        notification = Notification.objects.get(
            relate_instance=activity,
            status=Notification.Status.UNDONE
        )
        notification_status_change(notification, Notification.Status.DELETE)
        return

    if activity.status == Activity.Status.PROGRESSING:
        if activity.start.day == datetime.now().day and datetime.now() < activity.start + timedelta(days=1):
            pass
        else:
            raise ActivityException("活动已于一天前开始，不能取消。")

    if activity.status == Activity.Status.CANCELED:
        raise ActivityException("活动已取消。")

    org = Organization.objects.select_for_update().get(
        organization_id=request.user
    )

    activity.status = Activity.Status.CANCELED
    notifyActivity(activity.id, "modification_par",
                   f"您报名的活动{activity.title}已取消。")
    notification = Notification.objects.get(
        relate_instance=activity,
        typename=Notification.Type.NEEDDO
    )
    notification_status_change(notification, Notification.Status.DELETE)

    # 活动取消后，曾将所有相关状态变为申请失败

    _remove_activity_jobs(activity)
    activity.save()


def withdraw_activity(request, activity: Activity):

    np = Person.objects.get_by_user(request.user)
    participant = Participation.objects.select_for_update().get(
        SQ.sq(Participation.activity, activity),
        SQ.sq(Participation.person, np),
        status__in=[
            Activity.Status.WAITING,
            Participation.AttendStatus.APPLYING,
            Participation.AttendStatus.APPLYSUCCESS,
            Participation.AttendStatus.CANCELED,
        ],
    )
    if participant.status == Participation.AttendStatus.CANCELED:
        raise ActivityException("已退出活动。")
    participant.status = Participation.AttendStatus.CANCELED
    activity.current_participants -= 1

    participant.save()
    activity.save()


@transaction.atomic
def create_participate_infos(activity: Activity, persons: Iterable[Person], **fields):
    '''批量创建一系列参与信息，并返回创建的参与信息'''
    participantion = [
        Participation(**dict([
            (SQ.f(Participation.activity), activity),
            (SQ.f(Participation.person), person),
        ]), **fields) for person in persons
    ]
    return Participation.objects.bulk_create(participantion)


@transaction.atomic
def _update_new_participants(activity: Activity, new_participant_uids: list[str]) -> int:
    '''更新活动的参与者，返回新增的参与者数量，不修改活动'''
    status = Participation.AttendStatus.ATTENDED
    participants = SQ.qsvlist(SQ.sfilter(Participation.activity, activity).filter(
        status=status).select_for_update(), Participation.person)
    # 获取需要添加的参与者
    new_participant_nps = SQ.mfilter(Person.person_id, User.username,
                                     IN=new_participant_uids)
    new_participant_nps = new_participant_nps.exclude(id__in=participants)
    # 此处必须执行查询，否则是lazy query，会导致后面的bulk_increase_YQPoint出错
    new_participant_ids = SQ.qsvlist(new_participant_nps, Person.person_id)
    new_participants = User.objects.filter(id__in=new_participant_ids)
    # 为添加的参与者增加元气值
    point = activity.eval_point()
    User.objects.bulk_increase_YQPoint(
        new_participants, point, '参加活动', YQPointRecord.SourceType.ACTIVITY)
    create_participate_infos(activity, new_participant_nps, status=status)
    return len(new_participant_nps)


@transaction.atomic
def _delete_outdate_participants(activity: Activity, new_participant_uids: list[str]):
    '''删除过期的参与者，收回元气值，返回删除的参与者的数量，不修改活动'''
    # 获取需要删除的参与者
    participation = SQ.sfilter(Participation.activity, activity).filter(
        status=Participation.AttendStatus.ATTENDED).select_for_update()
    removed_participation = participation.exclude(
        SQ.mq(Participation.person, Person.person_id, User.username,
              IN=new_participant_uids))
    removed_participant_ids = SQ.qsvlist(removed_participation,
                                         Participation.person, Person.person_id)
    removed_participants = User.objects.filter(id__in=removed_participant_ids)
    # 为删除的参与者撤销元气值发放
    point = activity.eval_point()
    User.objects.bulk_withdraw_YQPoint(removed_participants, point, 
        '撤销参加活动', YQPointRecord.SourceType.CONSUMPTION)
    return removed_participation.delete()[0]


@transaction.atomic
def modify_participants(activity: Activity, new_participant_uids: list[str]):
    '''将参与信息修改为指定的参与者，参与者已经检查合法性，暂不允许删除'''
    new_uids = new_participant_uids
    # activity.current_participants -= _delete_outdate_participants(activity, new_uids)
    activity.current_participants += _update_new_participants(activity, new_uids)
    activity.save()


def weekly_summary_orgs() -> QuerySet[Organization]:
    '''允许进行每周总结的组织'''
    VALID_ORG_TYPES = ['团委', '学学学委员会', '学学学学会', '学生会']
    return SQ.mfilter(Org.otype, OrgType.otype_name, IN=VALID_ORG_TYPES)


def available_participants() -> QuerySet[User]:
    '''允许参与活动的人'''
    return SQ.mfilter(User.id, IN=SQ.qsvlist(Person.objects.activated(), Person.person_id))
