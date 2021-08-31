from threading import current_thread
from django.db.models import F
from django.http import JsonResponse, HttpResponse, QueryDict  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库

from app.models import Organization, NaturalPerson, YQPointDistribute, TransferRecord, User, Activity, Participant, Notification
from app.wechat_send import publish_notifications
from app.forms import YQPointDistributionForm
from boottest.hasher import MySHA256Hasher
from app.notification_utils import bulk_notification_create
from boottest import local_dict

from random import sample
from numpy.random import choice

from app.scheduler import scheduler, register_job

from urllib import parse, request as urllib2
import json

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
    # print(f"Change Activity Job works: aid: {aid}, cur_status: {cur_status}, to_status: {to_status}\n")
    # with open("/Users/liuzhanpeng/working/yp/YPPF/logs/error.txt", "a+") as f:
    #     f.write(f"aid: {aid}, cur_status: {cur_status}, to_status: {to_status}\n")
    #     f.close()
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
                    """
                    投点时使用
                    if activity.source == Activity.YQPointSource.COLLEGE:
                        draw_lots(activity)
                    else:
                        weighted_draw_lots(activity)
                    """
                draw_lots(activity)


            # 活动变更为进行中时，修改参与人参与状态
            elif activity.status == Activity.Status.PROGRESSING:
                if activity.need_checkin:
                    Participant.objects.filter(activity_id=aid, status=Participant.AttendStatus.APLLYSUCCESS).update(status=Participant.AttendStatus.UNATTENDED)
                else:
                    Participant.objects.filter(activity_id=aid, status=Participant.AttendStatus.APLLYSUCCESS).update(status=Participant.AttendStatus.ATTENDED)


            # 结束，计算积分    
            else:
                hours = (activity.end - activity.start).seconds / 3600
                participants = Participant.objects.filter(activity_id=aid, status=Participant.AttendStatus.ATTENDED)
                NaturalPerson.objects.filter(id__in=participants.values_list('person_id', flat=True)).update(bonusPoint=F('bonusPoint') + hours)

            activity.save()


    except Exception as e:
        # print(e)



        # TODO send message to admin to debug
        # with open("/Users/liuzhanpeng/working/yp/YPPF/logs/error.txt", "a+") as f:
        #     f.write(str(e) + "\n")
        #     f.close()
        pass


"""
需要在 transaction 中使用
所有涉及到 activity 的函数，都应该先锁 activity
"""
def draw_lots(activity):
    participants_applying = Participant.objects.filter(activity_id=activity.id, status=Participant.AttendStatus.APPLYING)
    l = len(participants_applying)

    participants_applySuccess = Participant.objects.filter(activity_id=activity.id, status=Participant.AttendStatus.APLLYSUCCESS)
    engaged = len(participants_applySuccess)

    leftQuota = activity.capacity - engaged

    if l <= leftQuota:
        Participant.objects.filter(activity_id=activity.id, status=Participant.AttendStatus.APPLYING).update(status=Participant.AttendStatus.APLLYSUCCESS)
    else:
        lucky_ones = sample(range(l), leftQuota)
        for i, participant in enumerate(Participant.objects.select_for_update().filter(activity_id=activity.id, status=Participant.AttendStatus.APPLYING)):
            if i in lucky_ones:
                participant.status = Participant.AttendStatus.APLLYSUCCESS
            else:
                participant.status = Participant.AttendStatus.APLLYFAILED
            participant.save()

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
def notifyActivity(aid:int, msg_type:str, msg=""):
    try:
        activity = Activity.objects.get(id=aid)
        if msg_type == "newActivity":
            msg = f"您关注的组织{activity.organization_id.oname}发布了新的活动：{activity.title}。\n"
            msg += f"开始时间: {activity.start}\n"
            msg += f"活动地点: {activity.location}\n"
            subscribers = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            )
            receivers = [subscriber.person_id for subscriber in subscribers]
        elif msg_type == "remind":
            msg = f"您参与的活动 <{activity.title}> 即将开始。\n"
            msg += f"开始时间: {activity.start}\n"
            msg += f"活动地点: {activity.location}\n"
            participants = Participant.objects.filter(activity_id=aid, status=Participant.AttendStatus.APLLYSUCCESS)
            receivers = [participant.person_id.person_id for participant in participants]
        elif msg_type == 'modification_sub':
            subscribers = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            )
            receivers = [subscriber.person_id for subscriber in subscribers]
        elif msg_type == 'modification_par':
            participants = Participant.objects.filter(
                activity_id=aid, 
                status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.APPLYING]
            )
            receivers = [participant.person_id.person_id for participant in participants]
        elif msg_type == "modification_sub_ex_par":
            participants = Participant.objects.filter(
                activity_id=aid, 
                status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.APPLYING]
            )
            subscribers = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            )
            receivers =  set(subscribers) - set([participant.person_id for participant in participants])
        # 应该用不到了，调用的时候分别发给 par 和 sub
        # 主要发给两类用户的信息往往是不一样的
        elif msg_type == 'modification_all':
            participants = Participant.objects.filter(
                activity_id=aid, 
                status__in=[Participant.AttendStatus.APLLYSUCCESS, Participant.AttendStatus.APPLYING]
            )
            subscribers = NaturalPerson.objects.activated().exclude(
                id__in=activity.organization_id.unsubscribers.all()
            )
            receivers = set([participant.person_id for participant in participants]) | set(subscribers)
        else:
            raise ValueError
        success, _ = bulk_notification_create(
            receivers=list(receivers),
            sender=activity.organization_id.organization_id,
            typename=Notification.Type.NEEDREAD,
            title=Notification.Title.ACTIVITY_INFORM,
            content=msg,
            URL=f"/viewActivity/{aid}",
            relate_instance=activity,
            publish_to_wechat=True
        )
        assert success

    except Exception as e:
        # print(f"Notification {msg} failed. Exception: {e}")
        # TODO send message to admin to debug
        pass



@register_job(scheduler, 'interval', id="get weather per hour", hours=1)
def get_weather():
    # weather = urllib2.urlopen("http://www.weather.com.cn/data/cityinfo/101010100.html").read()
    try:
        city = "Beijing"
        key = local_dict["weather_api_key"]
        lang = "zh_cn"
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={key}&lang={lang}"
        load_json = json.loads(urllib2.urlopen(url, timeout=5).read()) # 这里面信息太多了，不太方便传到前端
        weather_dict = {
            "modify_time": datetime.now().__str__(),
            "description": load_json["weather"][0]["description"],
            "temp": str(round(float(load_json["main"]["temp"]) - 273.15)),
            "temp_feel": str(round(float(load_json["main"]["feels_like"]) - 273.15)),
            "icon": load_json["weather"][0]["icon"]
        }
        with open("weather.json", "w") as weather_json:
            json.dump(weather_dict, weather_json)
    except Exception as e:
        # 相当于超时
        print(str(e))
        # TODO: 增加天气超时的debug
        print("任务超时")
        return None
    else:
        return weather_dict
