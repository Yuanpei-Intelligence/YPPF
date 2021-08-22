"""
这个文件应该只被 /app/views.py 依赖
依赖于 /app/utils.py, /app/scheduler_func.py,

scheduler_func 依赖于 wechat_send 依赖于 utils

文件中参数存在 activity 的函数需要在 transaction.atomic() 块中进行。
如果存在预期异常，抛出 ActivityException，否则抛出其他异常
"""
from app.scheduler_func import scheduler, changeActivityStatus, notifyActivity
from datetime import datetime, timedelta
from app.utils import get_person_or_org
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
    NewOrganization,
    Comment,
    CommentPhoto,
    YQPointDistribute
)


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


def activity_base_check(request):

    context = dict()

    # title, introduction, location 创建时不能为空
    context['title'] = request.POST["title"]
    context['introduction'] = request.POST["introduction"]
    context['location'] = request.POST["location"]
    assert len(context['title']) > 0
    assert len(context['introduction']) > 0
    assert len(context['location']) > 0

    # url
    context['url'] = request.POST["URL"]

    # 预算，元气值支付模式，是否直接向学院索要元气值
    # 在审核通过后，这些不可修改
    context['budget'] = float(request.POST["budget"])
    signscheme = int(request.POST["signscheme"])
    if signscheme:
        context['bidding'] = True
    else:
        context['bidding'] = False

    # 向学院申请元气值
    from_college = request.POST["from_college"]
    if from_college == '1':
        context['from_college'] = True
    elif from_college == '0':
        context['from_college'] = False


    # examine_teacher 需要特殊检查
    context['examine_teacher'] = request.POST['examine_teacher']


    # 时间
    # datetime 这里有 bug，PM 不会把时间加上去，到时候考虑 patch ......
    act_start = datetime.strptime(request.POST["actstart"], '%m/%d/%Y %H:%M %p')  # 活动报名时间
    act_end = datetime.strptime(request.POST["actend"], '%m/%d/%Y %H:%M %p')  # 活动报名结束时间
    now_time = datetime.now()
    context['start'] = act_start
    context['end'] = act_end
    assert check_ac_time(act_start, act_end)

    # create 或者调整报名时间，都是要确保活动不要立刻截止报名
    if request.POST.get('edit') is None or request.POST.get('adjust_apply_ddl'):
        prepare_scheme = int(request.POST["prepare_scheme"])
        prepare_times = Activity.EndBeforeHours.prepare_times
        prepare_time = prepare_times[prepare_scheme]
        signup_end = act_start - timedelta(hours=prepare_time)
        assert now_time <= signup_end
        context['endbefore'] = prepare_scheme
        context['signup_end'] = signup_end
    else:
        # 修改但不调整报名截止时间，后面函数自己查
        context['adjust_apply'] = False

    # 人数限制
    capacity = request.POST.get("maxpeople")
    no_limit = request.POST.get("unlimited_capacity")
    if no_limit is not None:
        capacity = 10000
    if capacity is not None and capacity != '':
        capacity = int(capacity)
        assert capacity >= 0
    context['capacity'] = capacity

    # 价格
    aprice = float(request.POST["aprice"])
    assert int(aprice * 10) / 10 == aprice
    assert aprice >= 0
    context['aprice'] = aprice

    return context


def create_activity(request):

    context = activity_base_check(request)

    # 审批老师存在
    examine_teacher = NaturalPerson.objects.get(name=context['examine_teacher'])
    assert examine_teacher.identity == NaturalPerson.Identity.TEACHER
    # TODO 添加审核数据，通知老师


    # 检查完毕，创建活动
    org = get_person_or_org(request.user, 'Organization')
    activity = Activity.objects.create(
                    title=context['title'], organization_id=org,
                    examine_teacher=examine_teacher
                )
    activity.title = context['title']
    activity.introduction = context['introduction']
    activity.location = context['location']
    activity.capacity = context['capacity']
    activity.URL = context['url']
    activity.budget = context['budget']
    activity.start = context['start']
    activity.end = context['end']
    activity.YQPoint = context['aprice']
    activity.bidding = context['bidding']
    activity.apply_end = context['signup_end']
    if context['from_college']:
        activity.source = Activity.YQPointSource.COLLEGE
    activity.endbefore = context['endbefore']
    activity.save()

    return activity.id



    '''
    审核通过后，需要进行通知，并添加定时任务
    if activity.status == Activity.Status.APPLYING:
        notifyActivity(activity.id, "newActivity")

    TEST:
    right_run = datetime.now() + timedelta(seconds=5)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}", 
        run_date=right_run, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING])
、

    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}", 
        run_date=context['signup_end'], args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}", 
        run_date=context['act_start'], args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
        run_date=context['act_end'], args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
    '''




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

    context = activity_base_check(request)

    if context['examine_teacher'] == activity.examine_teacher.name:
        pass
    else:
        examine_teacher = NaturalPerson.objects.get(name=context['examine_teacher'])
        assert examine_teacher.identity == NaturalPerson.Identity.TEACHER
        activity.examine_teacher = examine_teacher
        # TODO
        # 修改审核记录，通知老师

    if context.get('adjust_apply') is not None:
        # 注意这里是不调整
        assert context['adjust_apply'] == False
        assert activity.apply_end < context['start'] - timedelta(hours=1)
    else:
        activity.apply_end = context['signup_end']

    activity.title = context['title']
    activity.introduction = context['introduction']
    activity.location = context['location']
    activity.capacity = context['capacity']
    activity.URL = context['url']
    activity.budget = context['budget']
    activity.start = context['start']
    activity.end = context['end']
    activity.YQPoint = context['aprice']
    activity.bidding = context['bidding']
    if context['from_college']:
        activity.source = Activity.YQPointSource.COLLEGE
    activity.save()



"""
对已经通过审核的活动进行修改
不能修改预算，元气值支付模式，审批老师
只能修改时间，地点，URL, 简介，向同学收取元气值时的元气值数量
"""
def modify_accepted_activity(request, activity):

    # TODO
    # 删除任务，注册新任务

    to_participants = [f"您参与的活动{activity.title}发生变化"]
    to_subscribers = [f"您关注的活动{activity.title}发生变化"]
    if activity.location != request.POST['location']:
        to_participants.append("活动地点修改为" + activity.location)
        activity.location = request.POST['location']

    # 不是学院来源时，价格可能会变
    if activity.source != Activity.YQPointSource.COLLEGE:
        aprice = float(request.POST['aprice'])
        assert int(aprice * 10) / 10 == aprice
        assert aprice >= 0
        if activity.YQPoint != aprice:
            to_subscribers.append("活动价格调整为" + str(aprice))
            to_participants.append("活动价格调整为" + str(aprice))
            activity.YQPoint = aprice

    # 时间改变
    act_start = datetime.strptime(request.POST["actstart"], '%m/%d/%Y %H:%M %p')
    now_time = datetime.now()
    assert now_time < act_start
    if request.POST.get('adjust_apply_ddl'):
        prepare_scheme = int(request.POST["prepare_scheme"])
        prepare_times = Activity.EndBeforeHours.prepare_times
        prepare_time = prepare_times[prepare_scheme]
        signup_end = act_start - timedelta(hours=prepare_time)
        assert now_time <= signup_end
        activity.apply_end = signup_end
        to_subscribers.append("活动报名截止时间调整为" + str(signup_end))
        to_participants.append("活动报名截止时间调整为" + str(signup_end))
    else:
        signup_end = activity.apply_end
        assert signup_end + timedelta(hours=1) < act_start
    
    if activity.start != act_start:
        to_subscribers.append("活动开始时间调整为" + str(act_start))
        to_participants.append("活动开始时间调整为" + str(act_start))
        activity.start = act_start

    if signup_end < now_time and activity.status == Activity.Status.WAITING:
        activity.status = Activity.Status.APPLYING


    if request.POST.get('unlimited_capacity'):
        capacity = 10000
    else:
        capacity = int(request.POST['capacity'])
        assert capacity > 0
    activity.capacity = capacity

    activity.end = datetime.strptime(request.POST["actend"], '%m/%d/%Y %H:%M %p')
    assert activity.start < activity.end
    activity.URL = request.POST['URL']
    activity.introduction = request.POST['introduction']
    activity.save()

    if activity.status == Activity.Status.APPLYING:
        scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}", 
            run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING], replace_existing=True)
    else:
        scheduler.add_job(notifyActivity, 'date', id=f"activity_{activity.id}_remind",
            run_date=activity.act_start - timedelta(minutes=15), args=[activity.id, 'remind'], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}", 
        run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
        run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)


    notifyActivity(activity.id, "modification_sub", "\n".join(to_subscribers))
    notifyActivity(activity.id, "modification_par", "\n".join(to_participants))



def accept_activity(request, activity):
    activity.status = Activity.Status.APPLYING

    if activity.source == Activity.YQPointSource.COLLEGE:
        organization_id = activity.organization_id_id
        organization = Organization.objects.select_for_update().get(id=organization_id)
        YP = Organization.objects.select_for_update().get(oname="元培学院")
        organization.YQPoint += activity.amount
        YP.YQPoint -= activity.amount

        record = TransferRecord.objects.create(
            proposer=YP, recipient=organization.organization_id
        )
        record.amount = amount
        record.message = f"From College"
        organization.YQPoint += float(amount)
        record.status = TransferRecord.TransferStatus.ACCEPTED
        record.time = str(datetime.now())
        record.corres_act = activity
        record.save()
        YP.save()
        organization.save()


    # 通知
    notifyActivity(activity.id, "newActivity")


    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}", 
        run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}", 
        run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}", 
        run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])

    # TODO
    # 审核状态更新
    # 通知审核完成

    activity.save()

# 调用的时候用 try
# 调用者把 activity_id 作为参数传过来
def applyActivity(request, activity):
    context = dict()
    context["success"] = False
    CREATE = True

    payer = NaturalPerson.objects.select_for_update().get(
        person_id=request.user
    )
    try:
        participant = Participant.objects.select_for_update().get(
            activity_id=activity, person_id=payer
        )
        CREATE = False
    except:
        pass
    if CREATE == False:
        assert participant.status == Participant.AttendStatus.CANCELED


    organization_id = activity.organization_id_id
    organization = Organization.objects.select_for_update().get(id=organization_id)
    YP = Organization.objects.select_for_update().get(oname="元培学院")


    if activity.source == Activity.YQPointSource.COLLEGE:
        amount = activity.YQPoint
        if not activity.bidding:
            if activity.current_participants < activity.capacity:
                activity.current_participants += 1
            else:
                raise ActivityException("活动已报满，请稍后再试。")
        else:
            activity.current_participants += 1
    else:
        if not activity.bidding:
            amount = float(activity.YQPoint)
            if activity.current_participants < activity.capacity:
                activity.current_participants += 1
            else:
                raise ActivityException("活动已报满，请稍后再试。")
        else:
            amount = float(request.POST['willingness'])
            if not activity.YQPoint <= amount <= activity.YQPoint * 3:
                raise ActivityException("投点范围为基础值的 1-3 倍")
            # 依然增加，此时current_participants统计的是报名的人数，是可以比总人数多的
            activity.current_participants += 1
            assert amount == int(amount * 10) / 10

        assert payer.YQPoint + payer.quota >= amount

        use_quota = amount
        if payer.quota >= amount:
            payer.quota -= amount
        else:
            use_quota = payer.quota
            amount -= payer.quota
            payer.quota = 0
            payer.YQPoint -= amount
        YP.YQPoint -= amount
        # 用配额的部分
        if use_quota > 0:
            record = TransferRecord.objects.create(
                proposer=request.user, recipient=organization.organization_id
            )
            record.amount = use_quota
            record.message = "quota"
            organization.YQPoint += amount
            record.status = TransferRecord.TransferStatus.ACCEPTED
            record.time = str(datetime.now())
            record.corres_act = activity
            record.save()
        # 用个人账户的部分
        if amount > 0:
            record = TransferRecord.objects.create(
                proposer=request.user, recipient=organization.organization_id
            )
            record.amount = amount
            record.message = "YQPoint"
            organization.YQPoint += amount
            record.status = TransferRecord.TransferStatus.ACCEPTED
            record.time = str(datetime.now())
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

    YP.save()
    participant.save()
    payer.save()
    activity.save()
    organization.save()


def cancel_activity(request, activity):

    if activity.status == activity.Status.PROGRESSING:
        if activity.start.day == datetime.now().day and datetime.now() < activity.start + timedelta(days=1):
            pass
        else:
            raise ActivityException("活动已于一天前开始，不能取消。")

    org = Organization.objects.select_for_update().get(
                organization_id=request.user
            )
    assert activity.organization_id == org
    YP = Organization.objects.select_for_update().get(oname="元培学院")


    if activity.YQPoint > 0:
        if activity.source == Activity.YQPointSource.COLLEGE:
            if org.YQPoint < activity.YQPoint:
                raise ActivityException("没有足够的元气值退还给学院，不能取消。")
            org.YQPoint -= activity.YQPoint
            YP.YQPoint += activity.YQPoint
            record = TransferRecord.objects.select_for_update().get(
                proposer=YP, status=TransferRecord.TransferStatus.ACCEPTED, corres_act=activity
            )
            record.status = TransferRecord.TransferStatus.REFUND
            record.save()
        else:
            records = TransferRecord.objects.select_for_update().filter(
                status=TransferRecord.TransferStatus.ACCEPTED, corres_act=activity
            )
            total_amount = 0
            for record in records:
                payer = record.proposer
                total_amount += record.amount
                if record.message == "quota":
                    payer.quota += amount
                    YP.YQPoint += amount
                else:
                    payer.YQPoint += amount
                record.status = TransferRecord.TransferStatus.REFUND
                record.save()

            if total_amount > org.YQPoint:
                raise ActivityException("没有足够的元气值退还给同学，不能取消。")
            org.YQPoint -= total_amount



    activity.status = Activity.Status.CANCELED
    participants = Participant.objects.select_for_update().filter(
            activity_id=activity
        )
    for participant in participants:
        participant.status = Participant.AttendStatus.APLLYFAILED
        participant.save()

    # TODO 取消审核评论
    scheduler.remove_job(f"activity_{activity.id}_remind")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.WAITING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.PROGRESSING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.END}")

    notifyActivity(activity.id, "modification_par", f"您报名的活动{activity.title}已取消。")


    activity.save()
    YP.save()
    org.save()



def withdraw_activity(request, activity):

    np = NaturalPerson.objects.select_for_update().get(person_id=request.user)
    org = Organization.objects.select_for_update().get(
        organization_id=activity.organization_id.organization_id
    )
    YP = Organization.objects.select_for_update().get(oname="元培学院")
    participant = Participant.objects.select_for_update().get(
        activity_id=activity,
        person_id=np,
        status__in=[
            Participant.AttendStatus.APPLYING,
            Participant.AttendStatus.APLLYSUCCESS,
        ],
    )
    participant.status = Participant.AttendStatus.CANCELED
    activity.current_participants -= 1

    if activity.source == Activity.YQPointSource.STUDENT and activity.YQPoint > 0:
        record = None
        half_refund = 1
        if activity.bidding:
            assert activity.status == Activity.Status.APPLYING
        if activity.status == Activity.Status.WAITING:
            if not datetime.now() < activity.start - timedelta(hours=1):
                raise ActivityException("活动即将开始，不能取消。")
            half_refund = 0.5

        # 使用 quota 交付的记录
        try:
            record = TransferRecord.objects.select_for_update().get(
                corres_act=activity,
                proposer=request.user,
                status=TransferRecord.TransferStatus.ACCEPTED,
                message='quota'
            )
        except:
            pass
        if record is not None:
            amount = record.amount * half_refund
            amount = int(10 * amount) * 0.1
            record.status = TransferRecord.TransferStatus.REFUND
            np.quota += amount
            YP.YQPoint += amount
            if org.YQPoint < amount:
                raise ActivityException("组织账户元气值不足，请与组织负责人联系。")
            org.YQPoint -= amount
            record.save()

        # 使用个人账户交付的记录
        record = None
        try:
            record = TransferRecord.objects.select_for_update().get(
                corres_act=activity,
                proposer=request.user,
                status=TransferRecord.TransferStatus.ACCEPTED,
                message='YQPoint'
            )
        except:
            pass
        if record is not None:
            amount = record.amount * half_refund
            amount = int(10 * amount) * 0.1
            record.status = TransferRecord.TransferStatus.REFUND
            np.YQPoint += amount
            if org.YQPoint < amount:
                raise ActivityException("组织账户元气值不足，请与组织负责人联系。")
            org.YQPoint -= amount
            record.save()


    YP.save()
    org.save()
    np.save()
    participant.save()
    activity.save()








