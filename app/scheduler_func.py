from apscheduler.schedulers.background import BackgroundScheduler
from django.dispatch.dispatcher import receiver
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job

from django.db.models import F
from django.http import JsonResponse, HttpResponse, QueryDict  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库

from app.models import Organization, NaturalPerson, YQPointDistribute, TransferRecord, User, Activity
from app.wechat_send import base_send_wechat, wechatNotifyActivity, publish_activity
from app.forms import YQPointDistributionForm

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")

def distribute_YQPoint_to_users(proposer, recipients, YQPoints, trans_time):
    '''
        内容：
        由proposer账户(默认为一个组织账户)，向每一个在recipients中的账户中发起数额为YQPoints的转账
        并且自动生成默认为ACCEPTED的转账记录以便查阅

        这里的recipients期待为一个Queryset，要么全为自然人，要么全为组织
        proposer默认为一个组织账户
    '''
    try:
        assert proposer.YQPoint >= recipients.count() * YQPoints
    except:
        # 说明此时proposer账户的元气值不足
        print(f"由{proposer}向自然人{recipients[:3]}...等{recipients.count()}个用户发放元气值失败，原因可能是{proposer}的元气值剩余不足")
    try:
        is_nperson = isinstance(recipients[0], NaturalPerson) # 不为自然人则为组织
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

    # 没有问题，找到要发放元气值的人和组织
    per_to_dis = NaturalPerson.objects.activated().filter(
        YQPoint__lte=distributer.per_max_dis_YQP)
    org_to_dis = Organization.objects.activated().filter(
        YQPoint__lte=distributer.org_max_dis_YQP).exclude(oname="元培学院")
    # 由学院账号给大家发放
    YPcollege = Organization.objects.get(oname="元培学院")

    distribute_YQPoint_to_users(proposer=YPcollege, recipients=per_to_dis, YQPoints=distributer.per_YQP, trans_time=trans_time)
    distribute_YQPoint_to_users(proposer=YPcollege, recipients=org_to_dis, YQPoints=distributer.org_YQP, trans_time=trans_time)
    end_time = datetime.now()
    
    debug_msg = f"已向{per_to_dis.count()}个自然人和{org_to_dis.count()}个组织转账，用时{(end_time - trans_time).seconds}s,{(end_time - trans_time).microseconds}microsecond\n"
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
                        run_date=distributer.start_time, args = [distributer])
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
        message =  "请先以超级账户登录后台后再操作！"
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
        message =  "请先以超级账户登录后台后再操作！"
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
def changeActivityStatus(aid, cur_status, to_status):
    try:
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)
            if cur_status is not None:
                assert cur_status == activity.status
            if cur_status == Activity.Status.APPLYING:
                assert to_status == Activity.Status.WAITING
            elif cur_status == Activity.Status.WAITING:
                assert to_status == Activity.Status.PROGRESSING
            elif cur_status == Activity.Status.PROGRESSING:
                assert to_status == Activity.Status.END
            else:
                raise ValueError

            activity.status = to_status
    
            if activity.status == Activity.Status.WAITING:
                if activity.bidding:
                    # TODO 元气值抽签
                    pass

                # 提醒参与者
                scheduler.add_job(notifyActivity, 'date', id=c,
                    run_date=activity.act_start - timedelta(minutes=15), args=[activity.id, 'remind'], replace_existing=True)


            # 活动变更为进行中时，修改参与人参与状态
            if activity.status == Activity.Status.PROGRESSING:
                participants = Participant.objects.filter(activity_id=aid, status=Participant.AttendStatus.APLLYSUCCESS)
                for participant in participants:
                    # TODO: 现在是都变成参加成功，暂时还没做签到
                    participant.status = Participant.AttendStatus.ATTENDED
                    participant.save()

            activity.save()


    except:
        # TODO send message to admin to debug
        pass

"""
使用方式：

scheduler.add_job(notifyActivityStart, "date", 
    id=f"activity_{aid}_{start_notification}", run_date, args)

"""
def notifyActivity(aid, msg_type, msg=None):
    try:
        activity = Activity.objects.get(id=aid)
        if msg_type == "newActivity":
            publish_activity(aid)
            return
        elif msg_type == "remind":
            msg = f"您参与的活动 <{activity.title}> 即将开始。\n"
            msg += f"开始时间: {activity.act_start}\n"
            msg += f"活动地点: {activity.location}\n"
            send_to = 'participants'
        elif msg_type == 'modification_sub':
            send_to = 'subscribers'
        elif msg_type == 'modification_par':
            send_to = 'participants'
        elif msg_type == 'modification_all':
            send_to = 'all'
        else:
            raise ValueError
        wechatNotifyActivity(aid, msg, send_to)
    except Exception as e:
        print(f"Notification {msg} failed. Exception: {e}")
        # TODO send message to admin to debug
        pass




