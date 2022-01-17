from app.models import (
    User,
    NaturalPerson, 
    Organization,
    YQPointDistribute,
    TransferRecord,
    Activity,
    Participant,
    Notification,
    Position,
)
from app.activity_utils import calcu_activity_bonus
from app.notification_utils import bulk_notification_create, notification_status_change
from app.wechat_send import publish_notifications, WechatMessageLevel, WechatApp
from app import log
from app.constants import *
from app.forms import YQPointDistributionForm
from boottest import local_dict

import json
import urllib.request
from random import sample
from numpy.random import choice

from django.db.models import F, Sum
from django.http import JsonResponse, HttpResponse, QueryDict  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库

# 引入定时任务还是放上面吧
from app.scheduler import scheduler


def send_to_persons(title, message, url='/index/'):
    sender = User.objects.get(username='zz00000')
    np = NaturalPerson.objects.all()
    receivers = User.objects.filter(id__in=np.values_list('person_id', flat=True))
    print(bulk_notification_create(
        receivers, sender, 
        Notification.Type.NEEDREAD, title, message, url,
        publish_to_wechat=True,
        publish_kws={'level': WechatMessageLevel.IMPORTANT},
        ))


def send_to_orgs(title, message, url='/index/'):
    sender = User.objects.get(username='zz00000')
    org = Organization.objects.all().exclude(otype__otype_id=0)
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
        YP = Organization.objects.get(oname=YQPoint_oname)
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

def distribute_YQPoint_to_users(proposer, recipients, YQPoints, trans_time):
    '''
        内容：
        由proposer账户(默认为一个小组账户)，向每一个在recipients中的账户中发起数额为YQPoints的转账
        并且自动生成默认为ACCEPTED的转账记录以便查阅
        这里的recipients期待为一个Queryset，要么全为自然人，要么全为小组
        proposer默认为一个小组账户
    '''
    try:
        assert proposer.YQPoint >= recipients.count() * YQPoints
    except:
        # 说明此时proposer账户的元气值不足
        print(f"由{proposer}向自然人{recipients[:3]}...等{recipients.count()}个用户发放元气值失败，原因可能是{proposer}的元气值剩余不足")
    try:
        is_nperson = isinstance(recipients[0], NaturalPerson)  # 不为自然人则为小组
    except:
        print("没有转账对象！")
        return
    # 更新元气值
    recipients.update(YQPoint=F('YQPoint') + YQPoints)
    proposer.YQPoint -= recipients.count() * YQPoints
    proposer.save()
    # 生成转账记录
    trans_msg = f"{proposer}向您发放了{YQPoints}元气值，请查收！"
    transfer_list = [TransferRecord(
        proposer=proposer.organization_id,
        recipient=(recipient.person_id if is_nperson else recipient.organization_id),
        amount=YQPoints,
        start_time=trans_time,
        finish_time=trans_time,
        message=trans_msg,
        status=TransferRecord.TransferStatus.ACCEPTED
    ) for recipient in recipients]
    TransferRecord.objects.bulk_create(transfer_list)


def distribute_YQPoint(distributer):
    '''
        调用distribute_YQPoint_to_users, 给大家发放元气值
        这个函数的内容：根据distributer，找到发放对象，调用函数完成发放，（统计时间）
        distributer应该为一个YQPointDistribute类的实例
    '''
    trans_time = distributer.start_time

    # 没有问题，找到要发放元气值的人和小组
    per_to_dis = NaturalPerson.objects.activated().filter(
        YQPoint__lte=distributer.per_max_dis_YQP)
    org_to_dis = Organization.objects.activated().filter(
        YQPoint__lte=distributer.org_max_dis_YQP).exclude(oname=YQPoint_oname)
    # 由学院账号给大家发放
    YPcollege = Organization.objects.get(oname=YQPoint_oname)

    distribute_YQPoint_to_users(proposer=YPcollege, recipients=per_to_dis, YQPoints=distributer.per_YQP,
                                trans_time=trans_time)
    distribute_YQPoint_to_users(proposer=YPcollege, recipients=org_to_dis, YQPoints=distributer.org_YQP,
                                trans_time=trans_time)
    end_time = datetime.now()

    debug_msg = f"已向{per_to_dis.count()}个自然人和{org_to_dis.count()}个小组转账，用时{(end_time - trans_time).seconds}s,{(end_time - trans_time).microseconds}microsecond\n"
    print(debug_msg)


def add_YQPoints_distribute(dtype):
    '''
    内容：
        用于注册已知type=dtype的发放元气值的实例
        每种类型（临时发放、每周发放、每两周发放）都必须只有一个正在应用的实例;
        在注册时，如果已经有另一个正在进行的、类型相同的定时任务，会覆盖
        暂时还没写怎么取消
    '''
    try:
        distributer = YQPointDistribute.objects.get(type=dtype, status=True)
    except Exception as e:
        print(f"按类型{dtype}注册任务失败，原因可能是没有状态为YES或者有多个状态为YES的发放实例\n" + str(e))
    if dtype == YQPointDistribute.DistributionType.TEMPORARY:
        # 说明此时是临时发放
        scheduler.add_job(distribute_YQPoint, "date", id="temporary_YQP_distribute",
                          run_date=distributer.start_time, args=[distributer])
    else:
        # 说明此时是定期发放
        scheduler.add_job(distribute_YQPoint, "interval", id=f"{dtype}weeks_interval_YQP_distribute",
                          weeks=distributer.type, next_run_time=distributer.start_time, args=[distributer])


def all_YQPoint_Distributions(request):
    '''
        一个页面，展现当前所有的YQPointDistribute类
    '''
    context = dict()
    context['YQPoint_Distributions'] = YQPointDistribute.objects.all()
    return render(request, "YQP_Distributions.html", context)


def YQPoint_Distribution(request, dis_id):
    '''
        显示，也可以更改已经存在的YQPointDistribute类
        更改后，如果应用状态status为True，会完成该任务的注册
        如果之前有相同类型的实例存在，注册会失败！
    '''
    dis = YQPointDistribute.objects.get(id=dis_id)
    dis_form = YQPointDistributionForm(instance=dis)
    if request.method == 'POST':
        post_dict = QueryDict(request.POST.urlencode(), mutable=True)
        post_dict["start_time"] = post_dict["start_time"].replace("T", " ")
        dis_form = YQPointDistributionForm(post_dict, instance=dis)
        if dis_form.is_valid():
            dis_form.save()
            if dis.status == True:
                # 在这里注册scheduler
                try:
                    add_YQPoints_distribute(dis.type)
                except:
                    print("注册定时任务失败，可能是有多个status为Yes的实例")
    context = dict()
    context["dis"] = dis
    context["dis_form"] = dis_form
    context["start_time"] = str(dis.start_time).replace(" ", "T")
    return render(request, "YQP_Distribution.html", context)


def new_YQP_distribute(request):
    '''
        创建新的发放instance，如果status为True,会尝试注册
    '''
    if not request.user.is_superuser:
        message = "请先以超级账户登录后台后再操作！"
        return render(request, "debugging.html", {"message": message})
    dis = YQPointDistribute()
    dis_form = YQPointDistributionForm()
    if request.method == 'POST':
        post_dict = QueryDict(request.POST.urlencode(), mutable=True)
        post_dict["start_time"] = post_dict["start_time"].replace("T", " ")
        dis_form = YQPointDistributionForm(post_dict, instance=dis)
        print(dis_form)
        print(dis_form.is_valid())
        if dis_form.is_valid():
            print("valid")
            dis_form.save()
            if dis.status == True:
                # 在这里注册scheduler
                try:
                    add_YQPoints_distribute(dis.type)
                except:
                    print("注册定时任务失败，可能是有多个status为Yes的实例")
        return redirect("YQPoint_Distributions")
    return render(request, "new_YQP_distribution.html", {"dis_form": dis_form})


def YQPoint_Distributions(request):
    if not request.user.is_superuser:
        message = "请先以超级账户登录后台后再操作！"
        return render(request, "debugging.html", {"message": message})
    dis_id = request.GET.get("dis_id", "")
    if dis_id == "":
        return all_YQPoint_Distributions(request)
    elif dis_id == "new":
        return new_YQP_distribute(request)
    else:
        dis_id = int(dis_id)
        return YQPoint_Distribution(request, dis_id)



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

@log.except_captured(True, record_args=True, source='scheduler_func[changeActivityStatus]修改活动状态')
@log.except_captured(True, AssertionError, record_args=True, status_code='Problem',
                 record_user=False, record_request_args=False,
                 source='scheduler_func[changeActivityStatus]检查活动状态')
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
            #         YP = Organization.objects.select_for_update().get(oname=YQPoint_oname)
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
    sender=activity.organization_id.organization_id
    typename = Notification.Type.NEEDREAD
    content=f'您好！您参与抽签的活动“{activity.title}”报名成功！请准时参加活动！'
    URL=f'/viewActivity/{activity.id}'
    if len(receivers)>0:
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


@log.except_captured(True, source='scheduler_func[notifyActivity]发送微信消息')
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


try:
    default_weather = local_dict['default_weather']
except:
    default_weather = None


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
        log.operation_writer(local_dict["system_log"], "天气更新异常,原因可能是local_dict中缺少weather_api_key:"+str(e), "scheduler_func[get_weather]", "Problem")        
        return None
    except Exception as e:
        log.operation_writer(local_dict["system_log"], "天气更新异常,未知错误", "scheduler_func[get_weather]", "Problem")
        return default_weather
    else:
        log.operation_writer(local_dict["system_log"], "天气更新成功", "scheduler_func[get_weather]")
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
            scheduler.add_job(get_weather, 'interval', id=current_job,
                                minutes=5, replace_existing=True)
            scheduler.add_job(
                changeAllActivities, "interval", id="activityStatusUpdater",
                minutes=5, replace_existing=True
            )
        except Exception as e:
            info = f"add scheduled job '{current_job}' failed, reason: {e}"
            log.operation_writer(local_dict["system_log"], info,
                            "scheduler_func[start_scheduler]", "Error")
            if debug: print(info)

    try:
        if debug: print("starting schduler in scheduler_func.py")
        scheduler.start()
    except Exception as e:
        info = f"start scheduler failed, reason: {e}"
        log.operation_writer(local_dict["system_log"], info,
                        "scheduler_func[start_scheduler]", "Error")
        if debug: print(info)
        scheduler.shutdown(wait=False)
        if debug: print("successfully shutdown scheduler")
    if debug: print("———————————————— End     :   Debug ————————————————")