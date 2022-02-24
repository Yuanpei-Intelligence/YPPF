'''
待废弃

confirm_transaction依赖了以下内容，暂时移动到了函数内
    from app.notification_utils import notification_create, notification_status_change
    from app.wechat_send import publish_notification, WechatApp
'''
from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    YQPointDistribute,
    TransferRecord,
    Notification,
)
from datetime import datetime, timedelta
from django.db.models import F

from app.scheduler import scheduler

__all__ = [
    # 'distribute_YQPoint',
    'add_YQPoints_distribute',
    'confirm_transaction',
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


@log.except_captured(source='YQPoint_utils[confirm_transaction]', record_user=True)
def confirm_transaction(request, tid=None, reject=None):
    # 导入关系不正常，可再优化
    from app.notification_utils import notification_create, notification_status_change
    from app.wechat_send import publish_notification, WechatApp
    context = dict()
    context["warn_code"] = 1  # 先假设有问题
    new_notification = None
    with transaction.atomic():
        try:
            record = TransferRecord.objects.select_for_update().get(
                id=tid, recipient=request.user
            )

        except Exception as e:

            context["warn_message"] = "交易遇到问题, 请联系管理员!" + str(e)
            return context

        if record.status != TransferRecord.TransferStatus.WAITING:
            context["warn_message"] = "交易已经完成, 请不要重复操作!"
            return context

        payer = record.proposer
        try:
            if hasattr(payer, "naturalperson"):
                payer = (
                    NaturalPerson.objects.activated()
                        .select_for_update()
                        .get(person_id=payer)
                )
            else:
                payer = Organization.objects.select_for_update().get(
                    organization_id=payer
                )
        except:
            context["warn_message"] = "交易对象不存在或已毕业, 请联系管理员!"
            return context

        recipient = record.recipient
        if hasattr(recipient, "naturalperson"):
            recipient = (
                NaturalPerson.objects.activated()
                    .select_for_update()
                    .get(person_id=recipient)
            )
        else:
            recipient = Organization.objects.select_for_update().get(
                organization_id=recipient
            )

        if reject is True:
            record.status = TransferRecord.TransferStatus.REFUSED
            payer.YQPoint += record.amount
            payer.save()
            context["warn_message"] = "拒绝转账成功!"
            new_notification = notification_create(
                receiver=record.proposer,
                sender=record.recipient,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.TRANSFER_FEEDBACK,
                content=f"{str(recipient)}拒绝了您的转账。",
                URL="/myYQPoint/",
            )
            notification_status_change(record.transfer_notification.get().id)
        else:
            record.status = TransferRecord.TransferStatus.ACCEPTED
            recipient.YQPoint += record.amount
            recipient.save()
            context["warn_message"] = "交易成功!"
            new_notification = notification_create(
                receiver=record.proposer,
                sender=record.recipient,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.TRANSFER_FEEDBACK,
                content=f"{str(recipient)}接受了您的转账。",
                URL="/myYQPoint/",
            )
            notification_status_change(record.transfer_notification.get().id)
        publish_notification(new_notification, app=WechatApp.TRANSFER)
        record.finish_time = datetime.now()  # 交易完成时间
        record.save()
        context["warn_code"] = 2

        return context

    context["warn_message"] = "交易遇到问题, 请联系管理员!"
    return context


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
        if hasattr(obj_user, "naturalperson"):  # 如果OneToOne Field在个人上
            lis[-1]["obj"] = obj_user.naturalperson.name
            lis[-1]["obj_url"] = "/stuinfo/?name=" + lis[-1]["obj"] + "+" + str(obj_user.id)
        else:
            lis[-1]["obj"] = obj_user.organization.oname
            lis[-1]["obj_url"] = "/orginfo/?name=" + lis[-1]["obj"]

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
