from unicodedata import category
from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    Activity,
    Notification,
    ActivityPhoto,
    Position,
    Participant,
)
from django.contrib.auth.models import User
from app.utils import get_person_or_org, if_image
from app.notification_utils import(
    notification_create,
    notification_status_change,
)
from app.wechat_send import WechatApp, WechatMessageLevel
from app.activity_utils import (
    changeActivityStatus, 
    ActivityException, 
    check_ac_time,
    notifyActivity,
)

from datetime import datetime, timedelta

from app.scheduler import scheduler

def course_activity_base_check(request):
    '''检查课程活动，是activity_base_check的简化版'''

    context = dict()

    context["title"] = request.POST["title"]
    # context["introduction"] = request.POST["introduction"] # 暂定不需要简介
    context["location"] = request.POST["location"]
    assert len(context["title"]) > 0
    # assert len(context["introduction"]) > 0 # 暂定不需要简介
    assert len(context["location"]) > 0

    # 时间
    act_start = datetime.strptime(request.POST["lesson_start"], "%Y-%m-%d %H:%M")  # 活动开始时间
    act_end = datetime.strptime(request.POST["lesson_end"], "%Y-%m-%d %H:%M")  # 活动结束时间
    context["start"] = act_start
    context["end"] = act_end
    assert check_ac_time(act_start, act_end)

    context["need_checkin"] = True # 默认需要签到

    return context


def create_single_course_activity(request):
    '''
    创建单次课程活动，是create_activity的简化版
    '''
    context = course_activity_base_check(request)
    # 查找是否有类似活动存在
    old_ones = Activity.objects.activated().filter(
        title=context["title"],
        start=context["start"],
        # introduction=context["introduction"], # 暂定不需要简介
        location=context["location"]
    )
    if len(old_ones) == 0:
        old_ones = Activity.objects.filter(
            title = context["title"],
            start = context["start"],
            # introduction = context["introduction"], # 暂定不需要简介
            location = context["location"],
            status = Activity.Status.REVIEWING,
        )
    if len(old_ones):
        assert len(old_ones) == 1, "创建活动时，已存在的相似活动不唯一"
        return old_ones[0].id, False
    # 默认刘欣悦老师审核
    examine_teacher = NaturalPerson.objects.get(
        name='刘欣悦', identity=NaturalPerson.Identity.TEACHER)
    # 检查完毕，创建活动
    org = get_person_or_org(request.user, "Organization")

    activity = Activity.objects.create(
                    title=context["title"],
                    organization_id=org,
                    examine_teacher=examine_teacher,
                    # introduction=context["introduction"],# 暂定不需要简介
                    location=context["location"],
                    start=context["start"],
                    end=context["end"],
                    category=1,
                    # capacity, URL, budget, YQPoint, bidding, 
                    # apply_reason, inner, source, end_before均为default
                )
    activity.need_checkin = True # 默认需要签到

    activity.recorded = True
    activity.status = Activity.Status.APPLYING

    # 让课程小组成员参与本活动
    
    positions = Position.objects.activated().filter(org=activity.organization_id)
    for p in positions:
        activity.current_participants += 1
        person = p.person
        participant = Participant.objects.create(
            activity_id=activity, person_id=person
        )
        participant.status = Participant.AttendStatus.APLLYSUCCESS
        participant.save()
    participant
    activity.save()

    notifyActivity(activity.id, "newActivity")

    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
        run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    # 活动状态修改
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}",
        run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
        run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
        run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
    activity.save()

    # 使用一张默认图片以便viewActivity, examineActivity等页面展示
    tmp_pic = '/static/assets/img/announcepics/1.JPG'
    ActivityPhoto.objects.create(image=tmp_pic, type=ActivityPhoto.PhotoType.ANNOUNCE, activity=activity)

    notification_create(
        receiver=examine_teacher.person_id,
        sender=request.user,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="您有一个单次课程活动待审批",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app": WechatApp.AUDIT},
    )

    return activity.id, True


def modify_course_activity(request, activity):
    '''
    修改单次课程活动信息，是modify_activity的简化版
    '''
    
    # 是否需要检查活动的status？
    # if activity.status not in [
    #     Activity.Status.APPLYING, Activity.Status.WAITING, 
    #     Activity.Status.REVIEWING
    # ]:
    #     raise ValueError
    
    context = course_activity_base_check(request)

    old_title = activity.title
    activity.title = context["title"]
    # activity.introduction = context["introduction"]# 暂定不需要简介
    old_location = activity.location
    activity.location = context["location"]
    
    old_start = activity.start
    activity.start = context["start"]
    old_end = activity.end
    activity.end = context["end"]

    activity.save()

    # 目前只要编辑了活动信息，无论活动处于什么状态，都通知全体选课同学
    # if activity.status != Activity.Status.APPLYING and activity.status != Activity.Status.WAITING:
    #     return
    
    to_participants = [f"您参与的书院课程活动{old_title}发生变化"] # FIXME: 目前是审核前后都允许修改title，也可以改成都不允许
    if old_title != activity.title:
        to_participants.append(f"活动更名为{activity.title}")
    if old_location != request.POST["location"]:
        to_participants.append("活动地点修改为" + request.POST["location"])

    # 时间改变
    if activity.start != old_start:
        to_participants.append(f"活动开始时间调整为{activity.start.strftime('%Y-%m-%d %H:%M')}")

    
    if activity.status == Activity.Status.APPLYING:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}",
            run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING], replace_existing=True)
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
        run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
        run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
        run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)

    notifyActivity(activity.id, "modification_par", "\n".join(to_participants))

def cancel_course_activity(request, activity):

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
            raise ActivityException("课程活动已于一天前开始，不能取消。")

    if activity.status == Activity.Status.CANCELED:
        raise ActivityException("课程活动已取消。")

    org = Organization.objects.select_for_update().get(
                organization_id=request.user
            )

    activity.status = Activity.Status.CANCELED
    # 目前只要取消了活动信息，无论活动处于什么状态，都通知全体选课同学
    notifyActivity(activity.id, "modification_par", 
    f"您报名的书院课程活动{activity.title}已取消（活动原定开始于{activity.start.strftime('%Y-%m-%d %H:%M')}）。")
    notification = Notification.objects.get(
        relate_instance=activity,
        typename=Notification.Type.NEEDDO
    )
    notification_status_change(notification, Notification.Status.DELETE)

    scheduler.remove_job(f"activity_{activity.id}_remind")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.WAITING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.PROGRESSING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.END}")

    activity.save()

