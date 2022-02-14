"""
activity_utils.py

这个文件应该只被 ./activity_views.py, ./scheduler_func.py 依赖
依赖于 ./utils.py, ./wechat_send.py, ./notification_utils.py

scheduler_func 依赖于 wechat_send 依赖于 utils

文件中参数存在 activity 的函数需要在 transaction.atomic() 块中进行。
如果存在预期异常，抛出 ActivityException，否则抛出其他异常
"""
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

hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])


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

@log.except_captured(True, record_args=True, source='activity_utils[changeActivityStatus]修改活动状态')
@log.except_captured(True, AssertionError, record_args=True, status_code=log.STATE_WARNING,
                 record_user=False, record_request_args=False,
                 source='activity_utils[changeActivityStatus]检查活动状态')
def changeActivityStatus(aid, cur_status, to_status):
    '''
    幂等；可能发生异常；包装器负责处理异常
    必须提供cur_status，则会在转换状态前检查前后状态，每次只能变更一个阶段
    即：报名中->等待中->进行中->结束
    状态不符合时，抛出AssertionError
    '''
    # print(f"Change Activity Job works: aid: {aid}, cur_status: {cur_status}, to_status: {to_status}\n")
    with transaction.atomic():
        activity = Activity.objects.select_for_update().get(id=aid)
        if cur_status is not None:
            assert cur_status == activity.status, f"希望的状态是{cur_status}，但实际状态为{activity.status}"
            if cur_status == Activity.Status.APPLYING:
                assert to_status == Activity.Status.WAITING, f"不能从{cur_status}变更到{to_status}"
            elif cur_status == Activity.Status.WAITING:
                assert to_status == Activity.Status.PROGRESSING, f"不能从{cur_status}变更到{to_status}"
            elif cur_status == Activity.Status.PROGRESSING:
                assert to_status == Activity.Status.END, f"不能从{cur_status}变更到{to_status}"
        else:
            raise AssertionError('未提供当前状态，不允许进行活动状态修改')

        if to_status == Activity.Status.WAITING:
            if activity.bidding:
                """
                投点时使用
                if activity.source == Activity.YQPointSource.COLLEGE:
                    draw_lots(activity)
                else:
                    weighted_draw_lots(activity)
                """
                draw_lots(activity)


        # 活动变更为进行中时，修改参与人参与状态
        elif to_status == Activity.Status.PROGRESSING:
            if activity.need_checkin:
                Participant.objects.filter(
                    activity_id=aid,
                    status=Participant.AttendStatus.APLLYSUCCESS
                ).update(status=Participant.AttendStatus.UNATTENDED)
            else:
                Participant.objects.filter(
                    activity_id=aid,
                    status=Participant.AttendStatus.APLLYSUCCESS
                ).update(status=Participant.AttendStatus.ATTENDED)

            # if not activity.valid:
            #     # 活动开始后，未审核自动通过
            #     activity.valid = True
            #     records = TransferRecord.objects.filter(
            #         status=TransferRecord.TransferStatus.PENDING,
            #         corres_act=activity,
            #     )
            #     total_amount = records.aggregate(nums=Sum('amount'))["nums"]
            #     if total_amount is None:
            #         total_amount = 0.0
            #     if total_amount > 0:
            #         organization_id = activity.organization_id_id
            #         organization = Organization.objects.select_for_update().get(id=organization_id)
            #         organization.YQPoint += total_amount
            #         organization.save()
            #         YP = Organization.objects.select_for_update().get(oname=YQP_ONAME)
            #         YP.YQPoint -= total_amount
            #         YP.save()
            #     records.update(
            #         status=TransferRecord.TransferStatus.ACCEPTED,
            #         finish_time=datetime.now()
            #     )

            #     notification = Notification.objects.get(
            #         relate_instance=activity,
            #         status=Notification.Status.UNDONE,
            #         title=Notification.Title.VERIFY_INFORM
            #     )
            #     notification_status_change(notification, Notification.Status.DONE)

        # 结束，计算积分    
        elif to_status == Activity.Status.END and activity.valid:
            point = calcu_activity_bonus(activity)
            participants = Participant.objects.filter(
                activity_id=aid, status=Participant.AttendStatus.ATTENDED)
            NaturalPerson.objects.filter(id__in=participants.values_list(
                'person_id', flat=True)).update(
                bonusPoint=F('bonusPoint') + point)

        # 过早进行这个修改，将被写到activity待执行的保存中，导致失败后调用activity.save仍会调整状态
        activity.status = to_status
        activity.save()


"""
需要在 transaction 中使用
所有涉及到 activity 的函数，都应该先锁 activity
"""



def draw_lots(activity):
    participants_applying = Participant.objects.filter(activity_id=activity.id,
                                                       status=Participant.AttendStatus.APPLYING)
    l = len(participants_applying)

    participants_applySuccess = Participant.objects.filter(
        activity_id=activity.id,
        status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.UNATTENDED, Participant.AttendStatus.ATTENDED]
    )
    engaged = len(participants_applySuccess)

    leftQuota = activity.capacity - engaged

    if l <= leftQuota:
        Participant.objects.filter(
            activity_id=activity.id,
            status__in=[Participant.AttendStatus.APPLYING, Participant.AttendStatus.APLLYFAILED]
        ).update(status=Participant.AttendStatus.APLLYSUCCESS)
        activity.current_participants = engaged + l
    else:
        lucky_ones = sample(range(l), leftQuota)
        activity.current_participants = activity.capacity
        for i, participant in enumerate(Participant.objects.select_for_update().filter(
                activity_id=activity.id,
                status__in=[Participant.AttendStatus.APPLYING, Participant.AttendStatus.APLLYFAILED]
        )):
            if i in lucky_ones:
                participant.status = Participant.AttendStatus.APLLYSUCCESS
            else:
                participant.status = Participant.AttendStatus.APLLYFAILED
            participant.save()
    #签到成功的转发通知和微信通知
    receivers = Participant.objects.filter(
            activity_id=activity.id,
            status=Participant.AttendStatus.APLLYSUCCESS
        ).values_list('person_id__person_id', flat=True)
    receivers = User.objects.filter(id__in=receivers)
    sender = activity.organization_id.organization_id
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
            publish_to_wechat=True,
            publish_kws={
                'app': WechatApp.TO_PARTICIPANT,
                'level': WechatMessageLevel.IMPORTANT,
            },
        )
    #抽签失败的同学发送通知
    receivers = Participant.objects.filter(
        activity_id=activity.id,
        status=Participant.AttendStatus.APLLYFAILED
    ).values_list('person_id__person_id', flat=True)
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
            publish_to_wechat=True,
            publish_kws={
                'app': WechatApp.TO_PARTICIPANT,
                'level': WechatMessageLevel.IMPORTANT,
            },
        )



"""
投点情况下的抽签，暂时不用
需要在 transaction 中使用
def weighted_draw_lots(activity):
    participants = Participant.objects().select_for_update().filter(activity_id=activity.id, status=Participant.AttendStatus.APPLYING)
    l = len(participants)
    if l <= activity.capacity:
        for participant in participants:
            participant.status = Participant.AttendStatus.APLLYSUCCESS
            participant.save()
    else:
        weights = []
        for participant in participants:
            records = TransferRecord.objects(),filter(corres_act=activity, status=TransferRecord.TransferStatus.ACCEPTED, person_id=participant.proposer)
            weight = 0
            for record in records:
                weight += record.amount
            weights.append(weight)
        total_weight = sum(weights)
        d = [weight/total_weight for weight in weights]
        lucky_ones = choice(l, activity.capacity, replacement=False, p=weights)
        for i, participant in enumerate(participants):
            if i in lucky_ones:
                participant.status = Participant.AttendStatus.APLLYSUCCESS
            else:
                participant.status = Participant.AttendStatus.APLLYFAILED
            participant.save()
"""

"""
使用方式：
scheduler.add_job(notifyActivityStart, "date",
    id=f"activity_{aid}_{start_notification}", run_date, args)
"""


@log.except_captured(True, source='activity_utils[notifyActivity]发送微信消息')
def notifyActivity(aid: int, msg_type: str, msg=""):
    try:
        activity = Activity.objects.get(id=aid)
        inner = activity.inner
        title = Notification.Title.ACTIVITY_INFORM
        if msg_type == "newActivity":
            title = activity.title
            msg = f"您关注的小组{activity.organization_id.oname}发布了新的活动。"
            msg += f"\n开始时间: {activity.start.strftime('%Y-%m-%d %H:%M')}"
            msg += f"\n活动地点: {activity.location}"
            subscribers = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            ).values_list('person_id', flat=True)
            receivers = User.objects.filter(id__in=subscribers)
            publish_kws = {"app": WechatApp.TO_SUBSCRIBER}  
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
                    return False
                else:
                    msg = f"您参与的活动 <{activity.title}> 即将开始。"
                    msg += f"\n开始时间: {activity.start.strftime('%Y-%m-%d %H:%M')}"
                    msg += f"\n活动地点: {activity.location}"
                    participants = Participant.objects.filter(activity_id=aid, status=Participant.AttendStatus.APLLYSUCCESS)
                    receivers = participants.values_list('person_id__person_id', flat=True)
                    receivers = User.objects.filter(id__in=receivers)
                    # receivers = [participant.person_id.person_id for participant in participants]
                    publish_kws = {"app": WechatApp.TO_PARTICIPANT}

                    if inner and publish_kws.get('app') == WechatApp.TO_SUBSCRIBER:
                        member_id_list = Position.objects.activated().filter(
                            org=activity.organization_id).values_list(
                                'person__person_id', flat=True)
                        receivers = receivers.filter(id__in=member_id_list)

                    success, _ = bulk_notification_create(
                        receivers=list(receivers),
                        sender=activity.organization_id.organization_id,
                        typename=Notification.Type.NEEDREAD,
                        title=title,
                        content=msg,
                        URL=f"/viewActivity/{aid}",
                        relate_instance=activity,
                        publish_to_wechat=True,
                        publish_kws=publish_kws,
                    )

                    return success

        elif msg_type == 'modification_sub':
            subscribers = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            ).values_list('person_id', flat=True)
            receivers = User.objects.filter(id__in=subscribers)
            publish_kws = {"app": WechatApp.TO_SUBSCRIBER} 
        elif msg_type == 'modification_par':
            participants = Participant.objects.filter(
                activity_id=aid,
                status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.APPLYING]
            )
            receivers = participants.values_list('person_id__person_id', flat=True)
            receivers = User.objects.filter(id__in=receivers)
            # receivers = [participant.person_id.person_id for participant in participants]
            publish_kws = {
                "app": WechatApp.TO_PARTICIPANT,
                "level": WechatMessageLevel.IMPORTANT,
            }
        elif msg_type == "modification_sub_ex_par":
            '''
                YWolfeee: 查询策略为，拿到NP list
                拿到NP list中的person_id_id字段，作为一个list来操作
                直接访问一次user表得到user list，而不是通过for循环每一个进行一次
                要知道 [NP.user for NP in NP_list]的查询速度是O(xy),其中x是NP_list长度，y是User表长度
                而 User.objects.filter(id__in = [NP_person_id_id_list])则是O(y)
            '''
            # ———————————————— 拿参与者的user_id ————————————————
            participant_person_id = Participant.objects.filter(
                activity_id=aid,
                status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.APPLYING]
            ).prefetch_related("person_id_id").values_list("person_id_id", flat=True) # 拿的是person_id
            participant_user_id = NaturalPerson.objects.activated().filter(id__in = participant_person_id).values_list(
                "person_id_id",flat=True)   # 这回拿到的是user_id

            #  ———————————————— 拿订阅者的user_id ————————————————
            subscribers_user_id = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            ).values_list("person_id_id", flat=True )  # 拿的是user_id

            # ———————————————— 获取对应的User QuerySet ————————————————
            receiver_id_list = list(set(subscribers_user_id) - set(participant_user_id))
            receivers = User.objects.filter(id__in = receiver_id_list)

            # ↓这么写特别慢！
            #receivers = list(set(subscribers) - set([participant.person_id for participant in participants]))
            #receivers = [receiver.person_id for receiver in receivers]
            publish_kws = {"app": WechatApp.TO_SUBSCRIBER} 

        # 应该用不到了，调用的时候分别发给 par 和 sub
        # 主要发给两类用户的信息往往是不一样的
        elif msg_type == 'modification_all':
            # ———————————————— 拿参与者的user_id ————————————————
            participant_person_id = Participant.objects.filter(
                activity_id=aid,
                status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.APPLYING]
            ).values_list("person_id_id", flat=True) # 拿的是person_id
            participant_user_id = NaturalPerson.objects.activated().filter(
                id__in=participant_person_id).values_list(
                    "person_id_id", flat=True)   # 这回拿到的是user_id

            #  ———————————————— 拿订阅者的user_id ————————————————
            subscribers_user_id = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            ).values_list("person_id_id", flat=True )  # 拿的是user_id

            # ———————————————— 获取对应的User QuerySet ————————————————
            receiver_id_list = list(set(subscribers_user_id) | set(participant_user_id))
            receivers = User.objects.filter(id__in = receiver_id_list)

            # ↓这么写特别慢！
            # receivers = set([participant.person_id for participant in participants]) | set(subscribers)
            # receivers = [receiver.person_id for receiver in receivers]
            publish_kws = {"app": WechatApp.TO_SUBSCRIBER} 
        else:
            raise ValueError(f"msg_type参数错误: {msg_type}")
        
        # 现在必须保证到此处时receivers是一个queryset, 不过也有好处就是更统一了
        # 参与者总是收到消息, 但订阅者消息只会发给内部
        if inner and publish_kws.get('app') == WechatApp.TO_SUBSCRIBER:
            member_id_list = Position.objects.activated().filter(
                org=activity.organization_id).values_list(
                    'person__person_id', flat=True)
            receivers = receivers.filter(id__in=member_id_list)

        success, _ = bulk_notification_create(
            receivers=list(receivers),
            sender=activity.organization_id.organization_id,
            typename=Notification.Type.NEEDREAD,
            title=title,
            content=msg,
            URL=f"/viewActivity/{aid}",
            relate_instance=activity,
            publish_to_wechat=True,
            publish_kws=publish_kws,
        )
        assert success, "批量创建通知并发送时失败"

    except Exception as e:
        raise


def get_activity_QRcode(activity):
    auth_code = hash_coder.encode(str(activity.id))
    url_components = [
        local_dict["url"]["login_url"].strip("/"),
        "checkinActivity",
        f"{activity.id}?auth={auth_code}",
    ]
    url = "/".join(url_components)
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
        publish_kws={"app": WechatApp.AUDIT},
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
        publish_kws={"app": WechatApp.AUDIT},
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
        YQP_center = Organization.objects.select_for_update().get(oname=YQP_ONAME)
        YQP_center.YQPoint -= activity.YQPoint
        YQP_center.save()
        amount = activity.YQPoint
        record = TransferRecord.objects.create(
            proposer=YQP_center.organization_id,
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
            YQP_center = Organization.objects.select_for_update().get(oname=YQP_ONAME)
            YQP_center.YQPoint -= total_amount
            YQP_center.save()
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
        person_list = User.objects.filter(id__in=records.values_list("proposer_id", flat=True))
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
        publish_kws={"app": WechatApp.AUDIT},
    )


    activity.save()


# 调用的时候用 try
# 调用者把 activity_id 作为参数传过来
def applyActivity(request, activity):
    '''这个函数在正常情况下只应该抛出提示错误信息的ActivityException'''
    context = dict()
    context["success"] = False

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
        participated = True
    except:
        participated = False
    if participated:
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
                YQP_center = Organization.objects.select_for_update().get(oname=YQP_ONAME)
                YQP_center.YQPoint -= amount
                YQP_center.save()
                record.status = TransferRecord.TransferStatus.ACCEPTED
            else:
                record.status = TransferRecord.TransferStatus.PENDING
            record.finish_time = datetime.now()
            record.corres_act = activity
            record.save()


    if not participated:
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
        YQP_center = Organization.objects.select_for_update().get(oname=YQP_ONAME)
        YQP_center.YQPoint += activity.YQPoint
        YQP_center.save()
        # activity 上了悲观锁，这里不用锁
        record = TransferRecord.objects.get(
            proposer=YQP_center,
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
                YQP_center = Organization.objects.select_for_update().get(oname=YQP_ONAME)
                YQP_center.YQPoint += total_amount
                YQP_center.save()
                person_list = User.objects.filter(id__in=records.values_list("proposer_id", flat=True))
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
            person_list = User.objects.filter(id__in=records.values_list("proposer_id", flat=True))
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
            YQP_center = Organization.objects.select_for_update().get(oname=YQP_ONAME)
            YQP_center.YQPoint += amount
            YQP_center.save()
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


def calcu_activity_bonus(activity):
    hours = (activity.end - activity.start).seconds / 3600
    try:
        invalid_hour = float(local_dict["thresholds"]["activity_point_invalid_hour"])
    except:
        invalid_hour = 24.0
    if hours > invalid_hour:
        return 0.0
    # 以标题筛选不记录积分的活动，包含筛选词时不记录积分
    try:
        invalid_letters = local_dict["thresholds"]["activity_point_invalid_titles"]
        assert isinstance(invalid_letters, list)
        for invalid_letter in invalid_letters:
            if invalid_letter in activity.title:
                return 0.0
    except:
        pass

    try:
        point_rate = float(local_dict["thresholds"]["activity_point_per_hour"])
    except:
        point_rate = 1.0
    point = point_rate * hours
    # 单次活动记录的积分上限，默认6
    try:
        max_point = float(local_dict["thresholds"]["activity_point"])
    except:
        max_point = 6.0
    return min(point, max_point)

