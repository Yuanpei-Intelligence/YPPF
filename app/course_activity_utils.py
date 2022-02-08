from unicodedata import category
from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    Position,
    Activity,
    TransferRecord,
    Participant,
    Notification,
    ActivityPhoto,
)
from django.contrib.auth.models import User
from app.utils import get_person_or_org, if_image
from app.notification_utils import(
    notification_create,
    bulk_notification_create,
    notification_status_change,
)
from app.wechat_send import WechatApp, WechatMessageLevel
from app.activity_utils import (
    changeActivityStatus, 
    ActivityException, 
    check_ac_time,
)
import io
import os
import base64
import qrcode

from random import sample
from datetime import datetime, timedelta
from boottest import local_dict
from django.db.models import Sum
from django.db.models import F

from app.scheduler import scheduler

def course_activity_base_check(request):
    '''正常情况下检查出错误会抛出不含错误信息的AssertionError，不抛出ActivityException
    基本完工'''

    context = dict()

    # title, introduction, location 创建时不能为空
    context["title"] = request.POST["title"]
    # context["introduction"] = request.POST["introduction"] # TODO
    context["location"] = request.POST["location"]
    assert len(context["title"]) > 0
    # assert len(context["introduction"]) > 0 # TODO
    assert len(context["location"]) > 0

    

    # url，就不支持了 http 了，真的没必要
    # context["url"] = request.POST["URL"]
    # if context["url"] != "":
    #     assert context["url"].startswith("http://") or context["url"].startswith("https://")

    # 预算
    # 在审核通过后不可修改
    # context["budget"] = float(request.POST["budget"]) # FIXME:??
    
    # 向学院申请元气值 # FIXME:??
    # from_college = request.POST["from_college"]
    # if from_college == "1":
    #     context["from_college"] = True
    # elif from_college == "0":
    #     context["from_college"] = False

    # examine_teacher 需要特殊检查
    context["examine_teacher"] = request.POST.get("examine_teacher")
    # 申请理由 # FIXME:??
    # context["apply_reason"] = request.POST.get("apply_reason", "")
    # if context["from_college"]:
    #     assert len(context["apply_reason"]) > 0

    # 时间
    act_start = datetime.strptime(request.POST["lesson_start"], "%Y-%m-%d %H:%M")  # 活动报名时间（？应该是活动开始时间）
    act_end = datetime.strptime(request.POST["lesson_end"], "%Y-%m-%d %H:%M")  # 活动报名结束时间（？应该是活动结束时间）
    context["start"] = act_start
    context["end"] = act_end
    assert check_ac_time(act_start, act_end)
    # 需要签到
    if request.POST.get("need_checkin"):
        context["need_checkin"] = True

    # 价格 # FIXME:??
    # aprice = float(request.POST["aprice"])
    # assert int(aprice * 10) / 10 == aprice
    # assert aprice >= 0
    # context["aprice"] = aprice

    # 图片 优先使用上传的图片 # FIXME:??
    # announcephoto = request.FILES.getlist("images")
    # if len(announcephoto) > 0:
    #     pic = announcephoto[0]
    #     assert if_image(pic) == 2
    # else:
    #     if request.POST.get("picture1"):
    #         pic = request.POST.get("picture1")
    #     elif request.POST.get("picture2"):
    #         pic = request.POST.get("picture2")
    #     elif request.POST.get("picture3"):
    #         pic = request.POST.get("picture3")
    #     elif request.POST.get("picture4"):
    #         pic = request.POST.get("picture4")
    #     else:
    #         pic = request.POST.get("picture5")

    # context["pic"] = pic


    return context


def create_single_course_activity(request):
    '''
    检查活动，合法时寻找该活动，不存在时创建
    返回(activity.id, created)

    ---
    检查不合格时抛出AssertionError
    - 不再假设ActivityException特定语义，暂不抛出该类异常

    基本完工
    '''
    context = course_activity_base_check(request)
    # 查找是否有类似活动存在
    old_ones = Activity.objects.activated().filter(
        title=context["title"],
        start=context["start"],
        # introduction=context["introduction"], # TODO
        location=context["location"]
    )
    if len(old_ones) == 0:
        old_ones = Activity.objects.filter(
            title = context["title"],
            start = context["start"],
            # introduction = context["introduction"], # TODO
            location = context["location"],
            status = Activity.Status.REVIEWING,
        )
    if len(old_ones):
        assert len(old_ones) == 1, "创建活动时，已存在的相似活动不唯一"
        return old_ones[0].id, False
    # 审批老师存在
    examine_teacher = NaturalPerson.objects.get(
        name=context["examine_teacher"], identity=NaturalPerson.Identity.TEACHER)
    # 检查完毕，创建活动
    org = get_person_or_org(request.user, "Organization")

    activity = Activity.objects.create(
                    title=context["title"],
                    organization_id=org,
                    examine_teacher=examine_teacher,
                    # introduction=context["introduction"],# TODO
                    location=context["location"],
                    # capacity=context["capacity"], # FIXME: 是多少无所谓？
                    # URL=context["url"],# FIXME: 需要吗？
                    # budget=context["budget"],# FIXME: 需要吗？
                    start=context["start"],
                    end=context["end"],
                    # YQPoint=context["aprice"], # FIXME: 需要吗？
                    # bidding=False, # FIXME: 需要吗？
                    # apply_reason=context["apply_reason"], # FIXME: 需要吗？
                    # inner=context["inner"], # FIXME: 需要吗？
                    category=1,
                )
    print("AFTER INSERTION")
    # if context["from_college"]: # FIXME: 需要吗？
    #     activity.source = Activity.YQPointSource.COLLEGE
    # activity.endbefore = context["endbefore"] # FIXME: 需要吗？
    if context.get("need_checkin"):
        activity.need_checkin = True
    activity.save()
    print("AFTER SAVE")
    # ActivityPhoto.objects.create(image=context["pic"], type=ActivityPhoto.PhotoType.ANNOUNCE, activity=activity) # FIXME: 需要吗？
    notification_create(
        receiver=examine_teacher.person_id,
        sender=request.user,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="您有一个单次课程活动待审批",
        URL=f"/examineActivity/{activity.id}", # FIXME:??
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app": WechatApp.AUDIT},
    )

    return activity.id, True


def modify_course_activity(request, activity):
    '''
    修改单次活动信息

    ---

    基本完工，还差通知和scheduler的部分
    '''
    if activity.status not in [ # FIXME: ??
        Activity.Status.APPLYING, Activity.Status.WAITING, 
        Activity.Status.REVIEWING
    ]:
        raise ValueError
    
    context = course_activity_base_check(request)

    old_title = activity.title
    activity.title = context["title"]
    activity.introduction = context["introduction"]
    old_location = activity.location
    activity.location = context["location"]
    # activity.capacity = context["capacity"]

    activity.URL = context["url"]
    activity.budget = context["budget"]
    old_start = activity.start
    activity.start = context["start"]
    old_end = activity.end
    activity.end = context["end"]

    # activity.YQPoint = context["aprice"]
    # activity.bidding = context["bidding"]
    # activity.apply_reason = context["apply_reason"]
    # old_source = activity.source
    # if context["from_college"]:
    #     activity.source = Activity.YQPointSource.COLLEGE
    # else:
    #     activity.source = Activity.YQPointSource.STUDENT
    if context.get("need_checkin"):
        activity.need_checkin = True
    else:
        activity.need_checkin = False
    # if context.get("inner"):
    #     activity.inner = True
    # else:
    #     activity.inner = False
    activity.save()

    # 图片
    if context.get("pic") is not None:
        pic = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
        pic.image = context["pic"]
        pic.save()
    

    if activity.status != Activity.Status.APPLYING and activity.status != Activity.Status.WAITING: # FIXME: ??
        return
    
    to_participants = [f"您参与的书院课程活动{old_title}发生变化"] # FIXME: 目前是审核前后都允许修改title，也可以改成都不允许
    if old_title != activity.title:
        to_participants.append(f"活动更名为{activity.title}")
    if old_location != request.POST["location"]:
        to_participants.append("活动地点修改为" + request.POST["location"])

    # 不是学院来源时，价格可能会变 # FIXME：需要吗？
    # if activity.source != Activity.YQPointSource.COLLEGE:
    #     aprice = float(request.POST["aprice"])
    #     assert int(aprice * 10) / 10 == aprice
    #     assert aprice >= 0
    #     if activity.YQPoint != aprice:
    #         to_participants.append("活动价格调整为" + str(aprice))
    #         activity.YQPoint = aprice

    # 时间改变
    if activity.start != old_start:
        to_participants.append(f"活动开始时间调整为{activity.start.strftime('%Y-%m-%d %H:%M')}")

    '''
    # TODO：这些是在做什么？有必要吗？
    if activity.status == Activity.Status.APPLYING:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}",
            run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING], replace_existing=True)
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
        run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
        run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
        run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)
    '''

    notifyActivity(activity.id, "modification_par", "\n".join(to_participants)) # TODO: 通知