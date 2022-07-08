from app.utils_dependency import *
from app.models import (
    User,
    NaturalPerson,
    Organization,
    YQPointDistribute,
    TransferRecord,
    Notification,
)
from app.notification_utils import notification_create, notification_status_change
from app.wechat_send import publish_notification, WechatApp, WechatMessageLevel
from app.utils import get_classified_user

from datetime import datetime, timedelta
from django.db.models import F

from app.scheduler import scheduler

__all__ = [
    # 'distribute_YQPoint',
    'add_YQPoints_distribute',
    'create_transfer_record',
    'accept_transfer',
    'reject_transfer',
    'record2Display',
]

def _distribute_YQPoint_to_users(proposer, recipients, YQPoints, trans_time):
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
        print(
            f"由{proposer}向自然人{recipients[:3]}...等{recipients.count()}个用户"
            + "发放元气值失败，原因可能是{proposer}的元气值剩余不足"
        )
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
        recipient=recipient.get_user(),
        amount=YQPoints,
        start_time=trans_time,
        finish_time=trans_time,
        message=trans_msg,
        status=TransferRecord.TransferStatus.ACCEPTED
    ) for recipient in recipients]
    TransferRecord.objects.bulk_create(transfer_list)


def distribute_YQPoint(distributer):
    '''
        调用_distribute_YQPoint_to_users, 给大家发放元气值
        这个函数的内容：根据distributer，找到发放对象，调用函数完成发放，（统计时间）
        distributer应该为一个YQPointDistribute类的实例
    '''
    trans_time = distributer.start_time

    # 没有问题，找到要发放元气值的人和小组
    per_to_dis = NaturalPerson.objects.activated().filter(
        YQPoint__lte=distributer.per_max_dis_YQP)
    org_to_dis = Organization.objects.activated().filter(
        YQPoint__lte=distributer.org_max_dis_YQP).exclude(oname=YQP_ONAME)
    # 由学院账号给大家发放
    YPcollege = Organization.objects.get(oname=YQP_ONAME)

    _distribute_YQPoint_to_users(proposer=YPcollege,
                                 recipients=per_to_dis,
                                 YQPoints=distributer.per_YQP,
                                 trans_time=trans_time)
    _distribute_YQPoint_to_users(proposer=YPcollege,
                                 recipients=org_to_dis,
                                 YQPoints=distributer.org_YQP,
                                 trans_time=trans_time)
    end_time = datetime.now()

    diff_time = end_time - trans_time
    debug_msg = (
        f"已向{per_to_dis.count()}个自然人和{org_to_dis.count()}个小组转账，"
        + f"用时{diff_time.seconds}s,{diff_time.microseconds}microsecond\n"
    )
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
        print(f"按类型{dtype}注册任务失败，原因可能是没有状态为YES或者有多个状态为YES的发放实例\n{e}")
    if dtype == YQPointDistribute.DistributionType.TEMPORARY:
        # 说明此时是临时发放
        scheduler.add_job(distribute_YQPoint,
                          "date",
                          id="temporary_YQP_distribute",
                          run_date=distributer.start_time,
                          args=[distributer])
    else:
        # 说明此时是定期发放
        scheduler.add_job(distribute_YQPoint,
                          "interval",
                          id=f"{dtype}weeks_interval_YQP_distribute",
                          weeks=distributer.type,
                          next_run_time=distributer.start_time,
                          args=[distributer])


def create_transfer_record(payer: User, recipient: User, amount: float,
                           transaction_msg="", service=-1,
                           accept='no') -> MESSAGECONTEXT:
    '''
    创建一个转账记录，返回创建信息和记录id

    Parameters
    ----------
    service : TransferRecord.TransferType, 经过is_valid_service检查的服务类型
    accept : str, 立刻接收转账的行为，合法值包括`append`, `no`

    Returns
    -------
    MESSAGECONTEXT
    - 成功时具有record_id的额外字段
    - 创建成功且允许append追加接收时，具有accept_context的额外字段
    '''
    context, accepted = {}, False
    with transaction.atomic():
        # 上锁并查询余额
        payer_obj = get_classified_user(payer, update=True)
        if payer_obj.YQPoint < amount:
            return wrong(f'现存元气值余额为{payer_obj.YQPoint}, 不足以发起额度为{amount}的转账!')

        # 执行创建部分
        record: TransferRecord = TransferRecord.objects.create(
            proposer=payer,
            recipient=recipient,
            amount=amount,
            message=transaction_msg,
            rtype=(service if TransferRecord.TransferType.is_service(service)
                           else TransferRecord.TransferType.TRANSACTION),
            status=TransferRecord.TransferStatus.WAITING,
        )
        payer_obj.YQPoint -= amount
        payer_obj.save()

        notification = notification_create(
            receiver=recipient,
            sender=payer,
            typename=Notification.Type.NEEDDO,
            title=Notification.Title.TRANSFER_CONFIRM,
            content=transaction_msg or f'转账金额：{amount}',
            URL='/myYQPoint/',
            relate_TransferRecord=record,
        )
        # 更新返回的id
        context.update(record_id=record.id)

    # 如果立即追加接收转账逻辑
    if accept == 'append':
        accept_context = accept_transfer(record.id, notify=False)
        context.update(accept_context=accept_context)
        if accept_context[my_messages.CODE_FIELD] == SUCCEED:
            Notification.objects.filter(id=notification.id).update(
                title=Notification.Title.TRANSFER_INFORM)
            accepted = True

    # 发送微信提醒
    publish_notification(
        notification,
        app=WechatApp.TRANSFER,
        level=WechatMessageLevel.INFO if accepted else WechatMessageLevel.IMPORTANT,
    )
    return succeed('转账成功!' if accepted else
                   '成功发起转账，元气值将在对方确认后到账。', context)


def get_transfer_record(record_id, user=None) -> TransferRecord:
    '''获取、加锁并检查，失败时抛出对用户可见的`AssertionError`信息'''
    try:
        record = TransferRecord.objects.select_for_update().get(id=record_id)
    except:
        # 避免恶意的测试，不存在与无权限返回相同的报错信息
        raise AssertionError("没有权限调整该交易!")
    if user is not None and record.recipient != user:
        raise AssertionError("没有权限调整该交易!")
    if record.status != TransferRecord.TransferStatus.WAITING:
        raise AssertionError("交易已经完成, 请不要重复操作!")
    return record


def confirm_notifications(transaction_record):
    # 理应只有一个
    notification_status_change(
        transaction_record.transfer_notification.get(),
        Notification.Status.DONE
    )


@log.except_captured(wrong('交易意外失败, 请联系管理员!'), source='YQPoint_utils[accept_transfer]')
def accept_transfer(record_id, user=None, notify=True) -> MESSAGECONTEXT:
    with transaction.atomic():
        try:
            record = get_transfer_record(record_id, user)
        except AssertionError as e:
            return wrong(str(e))

        # 增加元气值
        recipient = get_classified_user(record.recipient, update=True)
        recipient.YQPoint += record.amount
        recipient.save()
        confirm_notifications(record)
        # 修改状态
        record.status = TransferRecord.TransferStatus.ACCEPTED
        # 交易完成时间
        record.finish_time = datetime.now()
        record.save()

        if notify:
            new_notification = notification_create(
                receiver=record.proposer,
                sender=record.recipient,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.TRANSFER_FEEDBACK,
                content=f'{recipient}接受了您的转账。',
                URL='/myYQPoint/',
            )
    if notify:
        publish_notification(new_notification, app=WechatApp.TRANSFER)
    return succeed('交易成功!')


@log.except_captured(wrong('交易意外失败, 请联系管理员!'), source='YQPoint_utils[reject_transfer]')
def reject_transfer(record_id, user=None, notify=True) -> MESSAGECONTEXT:
    with transaction.atomic():
        try:
            record = get_transfer_record(record_id, user)
        except AssertionError as e:
            return wrong(str(e))

        # 返还元气值
        payer = get_classified_user(record.proposer, update=True)
        payer.YQPoint += record.amount
        payer.save()
        confirm_notifications(record)
        # 修改状态
        record.status = TransferRecord.TransferStatus.REFUSED
        # 交易完成时间
        record.finish_time = datetime.now()
        record.save()

        if notify:
            recipient = get_classified_user(record.recipient)
            new_notification = notification_create(
                receiver=record.proposer,
                sender=record.recipient,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.TRANSFER_FEEDBACK,
                content=f'{recipient}拒绝了您的转账。',
                URL='/myYQPoint/',
            )
    if notify:
        publish_notification(new_notification, app=WechatApp.TRANSFER)
    return succeed('拒绝转账成功!')


@log.except_captured(source='YQPoint_utils[record2Display]')
def record2Display(record_list, user):  # 对应myYQPoint函数中的table_show_list
    lis = []
    amount = {"send": 0.0, "recv": 0.0}
    # 储存这个列表中所有record的元气值的和
    for record in record_list:
        lis.append({})

        # 确定类型
        record_type = "send" if record.proposer.username == user.username else "recv"

        # id
        lis[-1]["id"] = record.id

        # 时间
        lis[-1]["start_time"] = record.start_time.strftime("%Y-%m-%d %H:%M")
        if record.finish_time is not None:
            lis[-1]["finish_time"] = record.finish_time.strftime("%Y-%m-%d %H:%M")

        # 对象
        # 如果是给出列表，那么对象就是接收者

        obj_user = record.recipient if record_type == "send" else record.proposer
        lis[-1]["obj_direct"] = "To  " if record_type == "send" else "From"
        obj = get_classified_user(obj_user)
        lis[-1]["obj"] = obj.get_display_name()
        lis[-1]["obj_url"] = obj.get_absolute_url()

        # 金额
        lis[-1]["amount"] = record.amount
        amount[record_type] += record.amount

        # 留言
        lis[-1]["message"] = record.message
        lis[-1]["if_act_url"] = False
        if record.corres_act is not None:
            lis[-1]["message"] = "报名活动" + record.corres_act.title
            # TODO 这里还需要补充一个活动跳转链接

        # 状态
        if record.status == TransferRecord.TransferStatus.PENDING:
            # PENDING 就不对个人可见了，个人看到的就是元气值已经转过去了
            lis[-1]["status"] = "已接收"
        else:
            lis[-1]["status"] = record.get_status_display()

    # 对外展示为 1/10
    """
    统一在前端修改
    for key in amount:
        amount[key] = amount[key]/10
    """
    # 由于误差, 将amount调整为小数位数不超过2
    for key in amount.keys():
        amount[key] = round(amount[key], 1)
    return lis, amount
