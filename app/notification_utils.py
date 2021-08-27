from app.models import Notification
from app.wechat_send import publish_notification
from django.db import transaction
from datetime import datetime

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
        *,
        publish_to_wechat=False,
):
    """
    对于一个需要创建通知的事件，请调用该函数创建通知！
        receiver: org 或 nat_person，使用object.get获取的 user 对象
        sender: org 或 nat_person，使用object.get获取的 user 对象
        type: 知晓类 或 处理类
        title: 请在数据表中查找相应事件类型，若找不到，直接创建一个新的choice
        content: 输入通知的内容
        URL: 需要跳转到处理事务的页面

    注意事项：
        publish_to_wechat: bool 仅关键字参数
        - 你不应该输入这个参数，除非你清楚wechat_send.py的所有逻辑
        - 在最坏的情况下，可能会阻塞近10s
        - 简单来说，涉及订阅或者可能向多人连续发送类似通知时，都不要发送到微信
        - 在线程锁或原子锁内时，也不要发送

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
    )
    notification.save()
    if publish_to_wechat == True:
        publish_notification(notification)
    return notification