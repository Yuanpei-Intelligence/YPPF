from app.models import Notification
from app.wechat_send import publish_notification, publish_notifications
from boottest import local_dict
from app.utils import operation_writer
from django.db import transaction
from datetime import datetime
from boottest.hasher import MySHA256Hasher
from random import random

hasher = MySHA256Hasher("")

def notification_status_change(notification_or_id, to_status=None):
    """
    调用该函数以完成一项通知。对于知晓类通知，在接收到用户点击按钮后的post表单，该函数会被调用。
    对于需要完成的待处理通知，需要在对应的事务结束判断处，调用该函数。
    notification_id是notification的主键:id
    to_status是希望这条notification转变为的状态，包括
        DONE = (0, "已处理")
        UNDONE = (1, "待处理")
        DELETE = (2, "已删除")
    若不给to_status传参，默认为状态翻转：已处理<->未处理
    """
    context = dict()
    context["warn_code"] = 1
    context["warn_message"] = "在修改通知状态的过程中发生错误，请联系管理员！"

    if isinstance(notification_or_id, Notification):
        notification_id = notification_or_id.id
    else:
        notification_id = notification_or_id

    if to_status is None:  # 表示默认的状态翻转操作
        if isinstance(notification_or_id, Notification):
            now_status = notification_or_id.status
        else:
            try:
                notification = Notification.objects.get(id=notification_id)
                now_status = notification.status
            except:
                context["warn_message"] = "该通知不存在！"
                return context
        if now_status == Notification.Status.DONE:
            to_status = Notification.Status.UNDONE
        elif now_status == Notification.Status.UNDONE:
            to_status = Notification.Status.DONE
        else:
            to_status = Notification.Status.DELETE
            # context["warn_message"] = "已删除的通知无法翻转状态！"
            # return context    # 暂时允许

    with transaction.atomic():
        try:
            notification = Notification.objects.select_for_update().get(
                id=notification_id
            )
        except:
            context["warn_message"] = "该通知不存在！"
            return context
        if notification.status == to_status:
            context["warn_code"] = 2
            context["warn_message"] = "通知状态无需改变！"
            return context
        if (
                notification.status == Notification.Status.DELETE
                and notification.status != to_status
        ):
            context["warn_code"] = 2
            context["warn_message"] = "不能修改已删除的通知！"
            return context
        if to_status == Notification.Status.DONE:
            notification.status = Notification.Status.DONE
            notification.finish_time = datetime.now()  # 通知完成时间
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "您已成功阅读一条通知！"
        elif to_status == Notification.Status.UNDONE:
            notification.status = Notification.Status.UNDONE
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "成功设置一条通知为未读！"
        elif to_status == Notification.Status.DELETE:
            notification.status = Notification.Status.DELETE
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "成功删除一条通知！"
        return context


def notification_create(
        receiver,
        sender,
        typename,
        title,
        content,
        URL=None,
        relate_TransferRecord=None,
        relate_instance=None,
        anonymous_flag=False,
        *,
        publish_to_wechat=False,
        publish_kws=None,
):
    """
    对于一个需要创建通知的事件，请调用该函数创建通知！
        receiver: user, 对于org 或 nat_person，使用object.get获取的 user 对象
        sender: user, 对于org 或 nat_person，使用object.get获取的 user 对象
        type: 知晓类 或 处理类
        title: 请在数据表中查找相应事件类型，若找不到，直接创建一个新的choice
        content: 输入通知的内容
        URL: 需要跳转到处理事务的页面

    注意事项：
        publish_to_wechat: bool 仅关键字参数
        - 不要在循环中重复调用以发送，你可能需要看`bulk_notification_create`
        - 在线程锁或原子锁内时，也不要发送
        publish_kws: dict 仅关键字参数
        - 发送给微信的额外参数，主要是应用和发送等级，参考publish_notification即可

    现在，你应该在不急于等待的时候显式调用publish_notification(s)这两个函数，
        具体选择哪个取决于你创建的通知是一批类似通知还是单个通知
    """
    notification = Notification.objects.create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
        URL=URL,
        relate_TransferRecord=relate_TransferRecord,
        relate_instance=relate_instance,
        anonymous_flag=anonymous_flag,
    )
    if publish_to_wechat == True:
        if not publish_kws:
            publish_kws = {}
        publish_notification(notification, **publish_kws)
    return notification

def bulk_notification_create(
        receivers,
        sender,
        typename,
        title,
        content,
        URL=None,
        relate_TransferRecord=None,
        relate_instance=None,
        *,
        publish_to_wechat=False,
        publish_kws=None,
):
    """
    对于一个需要创建通知的事件，请调用该函数创建通知！
        receiver: Iter[user], 对于org 或 nat_person，请自行循环生成
        sender: user, 对于org 或 nat_person，使用object.get获取的 user 对象
        type: 知晓类 或 处理类
        title: 请在数据表中查找相应事件类型，若找不到，直接创建一个新的choice
        content: 输入通知的内容
        URL: 需要跳转到处理事务的页面

    注意事项：
        publish_to_wechat: bool 仅关键字参数
        - 在线程锁或原子锁内时，不要发送
        publish_kws: dict 仅关键字参数
        - 发送给微信的额外参数，主要是应用和发送等级，参考publish_notifications即可

    现在，你应该在不急于等待的时候显式调用publish_notification(s)这两个函数，
        具体选择哪个取决于你创建的通知是一批类似通知还是单个通知
    """
    bulk_identifier = hasher.encode(str(datetime.now()) + str(random()))
    try:
        notifications = [
            Notification(
                receiver=receiver,
                sender=sender,
                typename=typename,
                title=title,
                content=content,
                URL=URL,
                bulk_identifier=bulk_identifier,
                relate_TransferRecord=relate_TransferRecord,
                relate_instance=relate_instance,
            ) for receiver in receivers
        ]
        Notification.objects.bulk_create(notifications, 50)
        # bulk_create不调用save，因此不会自动生成绑定save方法的auto_now_add字段
        with transaction.atomic():
            # 添加了db索引 否则会锁整个表
            Notification.objects.select_for_update().filter(
                bulk_identifier=bulk_identifier).update(start_time=datetime.now())
        success = True
    except Exception as e:
        success = False
        operation_writer(local_dict['system_log'],
                        f'创建通知时发生错误：{e}, 识别码为{bulk_identifier}',
                        'notification_utils[bulk_notification_create]', 'Error')
    if success and publish_to_wechat:
        filter_kws = {"bulk_identifier": bulk_identifier}
        if not publish_kws:
            publish_kws = {}
        success = publish_notifications(filter_kws=filter_kws, **publish_kws)
    return success, bulk_identifier



