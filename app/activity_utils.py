"""
这个文件应该只被 /app/views.py 依赖
依赖于 /app/utils.py, /app/scheduler_func.py,

scheduler_func 依赖于 wechat_send 依赖于 utils

文件中参数存在 activity 的函数需要在 transaction.atomic() 块中进行。
如果存在预期异常，抛出 ActivityException，否则抛出其他异常
"""
from datetime import datetime, timedelta
from app.utils import get_person_or_org, if_image, calcu_activity_bonus
from app.notification_utils import(
    notification_create,
    bulk_notification_create,
    notification_status_change,
)
from django.contrib.auth.models import User
from app.wechat_send import WechatApp
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    OrganizationType,
    Position,
    Activity,
    TransferRecord,
    Participant,
    Notification,
    ModifyOrganization,
    Comment,
    CommentPhoto,
    YQPointDistribute,
    ActivityPhoto
)
import qrcode
import os
from boottest.hasher import MySHA256Hasher
from boottest.settings import MEDIA_ROOT, MEDIA_URL
from boottest import local_dict
from django.core.files import File
from django.core.files.base import ContentFile
import io
import base64
from django.db.models import Sum
from app.scheduler import scheduler
from app.scheduler_func import changeActivityStatus, notifyActivity
from django.db.models import F

hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])
YQPoint_oname = local_dict["YQPoint_source_oname"]

def get_activity_QRcode(activity):

    auth_code = hash_coder.encode(str(activity.id))
    url_components = [local_dict["url"]["login_url"].strip("/"), "checkinActivity", f"{activity.id}?auth={auth_code}"]
    url = "/".join(url_components)
    qr=qrcode.QRCode(version = 2,error_correction = qrcode.constants.ERROR_CORRECT_L,box_size=5,border=5)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    io_buffer = io.BytesIO()
    img.save(io_buffer, "png")
    data = base64.encodebytes(io_buffer.getvalue()).decode()
    return "data:image/png;base64," + str(data)

class  ActivityException(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


# 时间合法性的检查，检查时间是否在当前时间的一个月以内，并且检查开始的时间是否早于结束的时间，
def check_ac_time(start_time, end_time):
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
        assert context["url"].startswith("http://") or context["url"].startswith("https://")

    # 预算，元气值支付模式，是否直接向学院索要元气值
    # 在审核通过后，这些不可修改
    context["budget"] = float(request.POST["budget"])
    signscheme = int(request.POST["signscheme"])
    if signscheme:
        context["bidding"] = True
    else:
        context["bidding"] = False

    # 向学院申请元气值
    from_college = request.POST["from_college"]
    if from_college == "1":
        context["from_college"] = True
    elif from_college == "0":
        context["from_college"] = False


    # examine_teacher 需要特殊检查
    context["examine_teacher"] = request.POST.get("examine_teacher")
    # 申请理由
    context["apply_reason"] = request.POST.get("apply_reason", "")
    if context["from_college"]:
        assert len(context["apply_reason"]) > 0

    # 预报备
    context["recorded"] = False
    if request.POST.get("recorded"):
        context["recorded"] = True
        assert not context["from_college"]

    # 时间
    act_start = datetime.strptime(request.POST["actstart"], "%Y-%m-%d %H:%M")  # 活动报名时间
    act_end = datetime.strptime(request.POST["actend"], "%Y-%m-%d %H:%M")  # 活动报名结束时间
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

    # 价格
    aprice = float(request.POST["aprice"])
    assert int(aprice * 10) / 10 == aprice
    assert aprice >= 0
    context["aprice"] = aprice


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
            title = context["title"],
            start = context["start"],
            introduction = context["introduction"],
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
                    introduction=context["introduction"],
                    location=context["location"],
                    capacity=context["capacity"],
                    URL=context["url"],
                    budget=context["budget"],
                    start=context["start"],
                    end=context["end"],
                    YQPoint=context["aprice"],
                    bidding=context["bidding"],
                    apply_end=context["signup_end"],
                    apply_reason=context["apply_reason"],
                    inner=context["inner"],
                )
    if context["from_college"]:
        activity.source = Activity.YQPointSource.COLLEGE
    activity.endbefore = context["endbefore"]
    if context.get("need_checkin"):
        activity.need_checkin = True
    if context["recorded"]:
        # 预报备活动，先开放报名，再审批
        activity.recorded = True
        activity.status = Activity.Status.APPLYING
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

    if context.get("template_id"):
        template = Activity.objects.get(id=context["template_id"])
        photo = ActivityPhoto.objects.get(type=ActivityPhoto.PhotoType.ANNOUNCE, activity=template)
        photo.pk = None
        photo.id = None
        photo.activity = activity
        photo.save()
    else:
        ActivityPhoto.objects.create(image=context["pic"], type=ActivityPhoto.PhotoType.ANNOUNCE, activity=activity)

    notification_create(
        receiver=examine_teacher.person_id,
        sender=request.user,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="您有一个活动待审批",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app":WechatApp.AUDIT},
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

    """
    不允许修改审批老师
    if context["examine_teacher"] == activity.examine_teacher.name:
        pass
    else:
        examine_teacher = NaturalPerson.objects.get(
            name=context["examine_teacher"], identity=NaturalPerson.Identity.TEACHER)
        assert examine_teacher.identity == NaturalPerson.Identity.TEACHER
        activity.examine_teacher = examine_teacher
        # TODO
        # 修改审核记录，通知老师 

        notification = Notification.objects.get(relate_instance=activity, status=Notification.Status.UNDONE)
        notification_status_change(notification, Notification.Status.DELETE)

        notification_create(
            receiver=examine_teacher.person_id,
            sender=request.user,
            typename=Notification.Type.NEEDDO,
            title=Notification.Title.VERIFY_INFORM,
            content="您有一个活动待审批",
            URL=f"/examineActivity/{activity.id}",
            relate_instance=activity,
        )
    """


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
    activity.budget = context["budget"]
    activity.start = context["start"]
    activity.end = context["end"]
    activity.YQPoint = context["aprice"]
    activity.bidding = context["bidding"]
    activity.apply_reason = context["apply_reason"]
    if context["from_college"]:
        activity.source = Activity.YQPointSource.COLLEGE
    else:
        activity.source = Activity.YQPointSource.STUDENT
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

    # TODO
    # 删除任务，注册新任务

    to_participants = [f"您参与的活动{activity.title}发生变化"]
    # to_subscribers = [f"您关注的活动{activity.title}发生变化"]
    if activity.location != request.POST["location"]:
        to_participants.append("活动地点修改为" + request.POST["location"])
        activity.location = request.POST["location"]

    # 不是学院来源时，价格可能会变
    if activity.source != Activity.YQPointSource.COLLEGE:
        aprice = float(request.POST["aprice"])
        assert int(aprice * 10) / 10 == aprice
        assert aprice >= 0
        if activity.YQPoint != aprice:
            # to_subscribers.append("活动价格调整为" + str(aprice))
            to_participants.append("活动价格调整为" + str(aprice))
            activity.YQPoint = aprice

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
        to_participants.append(f"活动报名截止时间调整为{signup_end.strftime('%Y-%m-%d %H:%M')}")
    else:
        signup_end = activity.apply_end
        assert signup_end + timedelta(hours=1) <= act_start
    
    if activity.start != act_start:
        # to_subscribers.append(f"活动开始时间调整为{act_start.strftime('%Y-%m-%d %H:%M')}")
        to_participants.append(f"活动开始时间调整为{act_start.strftime('%Y-%m-%d %H:%M')}")
        activity.start = act_start

    if signup_end < now_time and activity.status == Activity.Status.WAITING:
        activity.status = Activity.Status.APPLYING


    if request.POST.get("unlimited_capacity"):
        capacity = 10000
    else:
        capacity = int(request.POST["maxpeople"])
        assert capacity > 0
        if capacity < len(Participant.objects.filter(
            activity_id=activity.id, 
            status=Participant.AttendStatus.APLLYSUCCESS
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


    if activity.status == Activity.Status.APPLYING:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}", 
            run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING], replace_existing=True)
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
        run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}", 
        run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
        run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)


    # if len(to_subscribers) > 1:
    #     notifyActivity(activity.id, "modification_sub_ex_par", "\n".join(to_subscribers))
    if len(to_participants) > 1:   
        notifyActivity(activity.id, "modification_par", "\n".join(to_participants))



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
        receiver=activity.organization_id.organization_id,
        sender=request.user,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACTIVITY_INFORM,
        content=f"您的活动{activity.title}已通过审批。",
        URL=f"/viewActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app":WechatApp.AUDIT},
    )

    if activity.status == Activity.Status.REVIEWING:

        now_time = datetime.now()
        if activity.end <= now_time:
            activity.status = Activity.Status.END
        elif activity.start <= now_time:
            activity.status = Activity.Status.PROGRESSING
            scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
                run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
        elif activity.apply_end <= now_time:
            activity.status = Activity.Status.WAITING
            scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
                run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
            scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}", 
                run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
        else:
            activity.status = Activity.Status.APPLYING
            notifyActivity(activity.id, "newActivity")
            scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
                run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
            scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}", 
                run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
            scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}", 
                run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING])
            scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
                run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)

    # 向学院申请元气值时，审批通过后转账
    if activity.source == Activity.YQPointSource.COLLEGE and activity.YQPoint > 0:
        organization_id = activity.organization_id_id
        organization = Organization.objects.select_for_update().get(id=organization_id)
        organization.YQPoint += activity.YQPoint
        organization.save()
        YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
        YP.YQPoint -= activity.YQPoint
        YP.save()
        amount = activity.YQPoint
        record = TransferRecord.objects.create(
            proposer=YP.organization_id, 
            recipient=organization.organization_id,
            rtype=TransferRecord.TransferType.ACTIVITY
        )
        record.amount = amount
        record.message = f"From College."
        record.status = TransferRecord.TransferStatus.ACCEPTED
        record.finish_time = datetime.now()
        record.corres_act = activity
        record.save()

    elif activity.recorded:
        # 预报备活动，修改转账记录为 accepted
        # 锁了 activity，不会有幻读
        records = TransferRecord.objects.filter(
            status=TransferRecord.TransferStatus.PENDING, 
            corres_act=activity,
        )
        total_amount = records.aggregate(nums=Sum('amount'))["nums"]
        if total_amount is None:
            total_amount = 0.0
        if total_amount > 0:
            organization_id = activity.organization_id_id
            organization = Organization.objects.select_for_update().get(id=organization_id)
            organization.YQPoint += total_amount
            organization.save()
            YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
            YP.YQPoint -= total_amount
            YP.save()
            records.update(
                status=TransferRecord.TransferStatus.ACCEPTED,
                finish_time=datetime.now()
            )

    if activity.status == Activity.Status.END:
        point = calcu_activity_bonus(activity)
        participants = Participant.objects.filter(
            activity_id=activity,
            status=Participant.AttendStatus.ATTENDED
        ).values_list("person_id", flat=True)
        NaturalPerson.objects.filter(id__in=participants).update(bonusPoint=F("bonusPoint") + point)

    activity.save()



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
        # Participant.objects.filter(
        #         activity_id=activity
        #     ).update(status=Participant.AttendStatus.APLLYFAILED)
        notifyActivity(activity.id, "modification_par", f"您报名的活动{activity.title}已取消。")
        activity.status = Activity.Status.CANCELED
        scheduler.remove_job(f"activity_{activity.id}_remind")
        scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.WAITING}")
        scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.PROGRESSING}")
        scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.END}")

        # 加退款逻辑 ( 只需要考虑学生 )
        records = TransferRecord.objects.filter(
            status=TransferRecord.TransferStatus.PENDING, 
            corres_act=activity,
        )
        person_list = User.objects.filter(id__in=records.values_list("proposer_id",flat=True))
        # person_list = [record.proposer.id for record in records]
        payers = NaturalPerson.objects.select_for_update().filter(person_id__in=person_list)
        for record in records:
            NaturalPerson.objects.filter(person_id=record.proposer).update(YQPoint=F("YQPoint") + record.amount)
        records.update(
            status=TransferRecord.TransferStatus.SUSPENDED,
            finish_time=datetime.now()
        )


    notification = notification_create(
        receiver=activity.organization_id.organization_id,
        sender=request.user,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACTIVITY_INFORM,
        content=f"您的活动{activity.title}被拒绝。",
        URL=f"/viewActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app":WechatApp.AUDIT},
    )


    activity.save()


# 调用的时候用 try
# 调用者把 activity_id 作为参数传过来
def applyActivity(request, activity):
    '''这个函数在正常情况下只应该抛出提示错误信息的ActivityException'''
    context = dict()
    context["success"] = False
    CREATE = True

    payer = NaturalPerson.objects.select_for_update().get(
        person_id=request.user
    )

    if activity.inner:
        position = Position.objects.activated().filter(person=payer, org=activity.organization_id)
        if len(position) == 0:
            # 按理说这里也是走不到的，前端会限制
            raise ActivityException(f"该活动是{activity.organization_id}内部活动，暂不开放对外报名。")

    try:
        participant = Participant.objects.select_for_update().get(
            activity_id=activity, person_id=payer
        )
        CREATE = False
    except:
        pass
    if CREATE == False:
        if (
            participant.status == Participant.AttendStatus.APLLYSUCCESS or
            participant.status == Participant.AttendStatus.APPLYING
        ):
            raise ActivityException("您已报名该活动。")
        elif participant.status != Participant.AttendStatus.CANCELED:
            raise ActivityException(f"您的报名状态异常，当前状态为：{participant.status}")
        


    if activity.source == Activity.YQPointSource.COLLEGE:
        if not activity.bidding:
            if activity.current_participants < activity.capacity:
                activity.current_participants += 1
            else:
                raise ActivityException("活动已报满，请稍后再试。")
        else:
            activity.current_participants += 1
    else:
        """
        存在投点的逻辑，暂时不用
        if not activity.bidding:
            amount = float(activity.YQPoint)
            if activity.current_participants < activity.capacity:
                activity.current_participants += 1
            else:
                raise ActivityException("活动已报满，请稍后再试。")
        else:
            amount = float(request.POST["willingness"])
            if not activity.YQPoint <= amount <= activity.YQPoint * 3:
                raise ActivityException("投点范围为基础值的 1-3 倍")
            # 依然增加，此时current_participants统计的是报名的人数，是可以比总人数多的
            activity.current_participants += 1
            assert amount == int(amount * 10) / 10
        """
        amount = float(activity.YQPoint)

        if amount > 0:
            if not payer.YQPoint >= amount:
                raise ActivityException(f"没有足够的元气值。您当前的元气值数量为 {payer.YQPoint}")

        if activity.bidding:
            activity.current_participants += 1
        else:
            if activity.current_participants < activity.capacity:
                activity.current_participants += 1
            else:
                raise ActivityException("活动已报满，请稍后再试。")

        if amount > 0:
            payer.YQPoint -= amount
            record = TransferRecord.objects.create(
                proposer=request.user, 
                recipient=activity.organization_id.organization_id,
                rtype=TransferRecord.TransferType.ACTIVITY
            )
            record.amount = amount
            record.message = f"报名参与活动{activity.title}。"

            if activity.valid:
                organization_id = activity.organization_id_id
                organization = Organization.objects.select_for_update().get(id=organization_id)
                organization.YQPoint += amount
                organization.save()
                YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
                YP.YQPoint -= amount
                YP.save()
                record.status = TransferRecord.TransferStatus.ACCEPTED
            else:
                record.status = TransferRecord.TransferStatus.PENDING
            record.finish_time = datetime.now()
            record.corres_act = activity
            record.save()


    if CREATE:
        participant = Participant.objects.create(
            activity_id=activity, person_id=payer
        )
    if not activity.bidding:
        participant.status = Participant.AttendStatus.APLLYSUCCESS
    else:
        participant.status = Participant.AttendStatus.APPLYING

    participant.save()
    payer.save()
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

    if activity.source == Activity.YQPointSource.COLLEGE and activity.YQPoint > 0:
        # 向学院申请，不允许预报备，不允许修改元气值数量
        if org.YQPoint < activity.YQPoint:
            raise ActivityException("没有足够的元气值退还给学院，不能取消。")
        org.YQPoint -= activity.YQPoint
        org.save()
        # 这里加个悲观锁能提高性能吗 ？
        YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
        YP.YQPoint += activity.YQPoint
        YP.save()
        # activity 上了悲观锁，这里不用锁
        record = TransferRecord.objects.get(
            proposer=YP, 
            status=TransferRecord.TransferStatus.ACCEPTED, 
            corres_act=activity
        )
        record.status = TransferRecord.TransferStatus.REFUND
        record.save()
    else:
        # 考虑两种情况，活动 valid，所有 record 都是 accepted
        if activity.valid:
            records = TransferRecord.objects.filter(
                status=TransferRecord.TransferStatus.ACCEPTED, 
                corres_act=activity).prefetch_related("proposer")
            total_amount = records.aggregate(nums=Sum('amount'))["nums"]
            if total_amount is None:
                total_amount = 0.0
            if total_amount > org.YQPoint:
                raise ActivityException("没有足够的元气值退还给同学，不能取消。")
            if total_amount > 0:
                org.YQPoint -= total_amount
                org.save()
                YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
                YP.YQPoint += total_amount
                YP.save()
                person_list = User.objects.filter(id__in=records.values_list("proposer_id",flat=True))
                # person_list = [record.proposer.id for record in records]
                payers = NaturalPerson.objects.select_for_update().filter(person_id__in=person_list)
                for record in records:
                    NaturalPerson.objects.filter(person_id=record.proposer).update(YQPoint=F("YQPoint") + record.amount)
                records.update(
                    status=TransferRecord.TransferStatus.REFUND,
                    finish_time=datetime.now()
                )
        else:
            # 都是 pending
            records = TransferRecord.objects.filter(
                status=TransferRecord.TransferStatus.PENDING, 
                corres_act=activity).prefetch_related("proposer")
            # person_list = [record.proposer.id for record in records]
            person_list = User.objects.filter(id__in=records.values_list("proposer_id",flat=True))
            payers = NaturalPerson.objects.select_for_update().filter(person_id__in=person_list)
            for record in records:
                NaturalPerson.objects.filter(person_id=record.proposer).update(YQPoint=F("YQPoint") + record.amount)
            records.update(
                status=TransferRecord.TransferStatus.SUSPENDED,
                finish_time=datetime.now()
            )



    activity.status = Activity.Status.CANCELED
    notifyActivity(activity.id, "modification_par", f"您报名的活动{activity.title}已取消。")
    notification = Notification.objects.get(
        relate_instance=activity,
        typename=Notification.Type.NEEDDO
    )
    notification_status_change(notification, Notification.Status.DELETE)


    # 注意这里，活动取消后，状态变为申请失败了
    # participants = Participant.objects.filter(
    #         activity_id=activity
    #     ).update(status=Participant.AttendStatus.APLLYFAILED)



    scheduler.remove_job(f"activity_{activity.id}_remind")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.WAITING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.PROGRESSING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.END}")

    activity.save()



def withdraw_activity(request, activity):

    np = NaturalPerson.objects.select_for_update().get(person_id=request.user)
    participant = Participant.objects.select_for_update().get(
        activity_id=activity,
        person_id=np,
        status__in=[
            Participant.AttendStatus.APPLYING,
            Participant.AttendStatus.APLLYSUCCESS,
            Participant.AttendStatus.CANCELED,
        ],
    )
    if participant.status == Participant.AttendStatus.CANCELED:
        raise ActivityException("已退出活动。")
    participant.status = Participant.AttendStatus.CANCELED
    activity.current_participants -= 1

    # 去掉了两个 check。一个是报名状态是申请中，一个是活动收取的元气值大于 0
    # 因为比较宽松的修改限制，上面两条不合适
    if activity.source == Activity.YQPointSource.STUDENT:
        half_refund = 1
        if activity.status == Activity.Status.WAITING:
            if not datetime.now() < activity.start - timedelta(hours=1):
                raise ActivityException("活动即将开始，不能取消。")
            half_refund = 0.5

        # 非预报备的记录 ( 一个活动只可能有两种之一 )
        try:
            record = TransferRecord.objects.select_for_update().get(
                corres_act=activity,
                proposer=request.user,
                # 活动未过审产生的 Pending 记录不需要考虑
                status=TransferRecord.TransferStatus.ACCEPTED,
                rtype=TransferRecord.TransferType.ACTIVITY
            )
            amount = record.amount * half_refund
            org = Organization.objects.select_for_update().get(
                organization_id=activity.organization_id.organization_id
            )
            if org.YQPoint < amount:
                raise ActivityException("小组账户元气值不足，请与小组负责人联系。")
            org.YQPoint -= amount
            org.save()
            record.status = TransferRecord.TransferStatus.REFUND
            record.save()
            np.YQPoint += amount
            YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
            YP.YQPoint += amount
            YP.save()
        except:
            pass

        # 预报备记录，状态为 Penging
        try:
            record = TransferRecord.objects.select_for_update().get(
                corres_act=activity,
                proposer=request.user,
                # 活动未过审产生的 Pending 记录不需要考虑
                status=TransferRecord.TransferStatus.PENDING,
                rtype=TransferRecord.TransferType.ACTIVITY
            )
            # 这里如果再退一半有没有问题？
            # 没啥问题，只是少了配额，不管小组和学院就好了，其实就是小组拿不到赔偿
            amount = record.amount * half_refund
            np.YQPoint += amount
            record.status = TransferRecord.TransferStatus.SUSPENDED
            record.save()
        except:
            pass

    participant.save()
    np.save()
    activity.save()









