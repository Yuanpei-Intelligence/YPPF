from random import random
from typing import Union, List
from datetime import datetime, timedelta

from generic.models import User
from boot.config import GLOBAL_CONFIG
from app.utils_dependency import *
from app.models import Notification
from app.extern.wechat import (
    publish_notification,
    publish_notifications,
    WechatApp,
    WechatMessageLevel,
)
from app.log import logger


hasher = MySHA256Hasher("")

__all__ = [
    'notification_status_change',
    'notification_create',
    'bulk_notification_create',
    'notification2Display',
]


def get_default_sender() -> User:
    return User.objects.get(username=GLOBAL_CONFIG.official_uid)


def notification_status_change(
    notification_or_id: Union[Notification, int],
    to_status: Notification.Status = None,
) -> MESSAGECONTEXT:
    """
    调用该函数以完成一项通知。对于知晓类通知，在接收到用户点击按钮后的post表单，该函数会被调用。
    对于需要完成的待处理通知，需要在对应的事务结束判断处，调用该函数。
    若不给to_status传参，默认为状态翻转：已处理<->未处理，已删除保持不变

    :param notification_or_id: 通知或其主键
    :type notification_or_id: Union[Notification, int]
    :param to_status: 希望这条notification转变为的状态，不填为翻转, defaults to None
    :type to_status: Notification.Status, optional
    :return: 执行情况的信息
    :rtype: MESSAGECONTEXT
    """
    context = wrong("在修改通知状态的过程中发生错误，请联系管理员！")

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
                return wrong("该通知不存在！", context)
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
            notification: Notification = \
                Notification.objects.select_for_update().get(id=notification_id)
        except:
            return wrong("该通知不存在！", context)
        if notification.status == to_status:
            return succeed("通知状态无需改变！", context)
        if (
            notification.status == Notification.Status.DELETE
            and notification.status != to_status
        ):
            return wrong("不能修改已删除的通知！", context)
        if to_status == Notification.Status.DONE:
            notification.status = Notification.Status.DONE
            notification.finish_time = datetime.now()  # 通知完成时间
            notification.save()
            succeed("您已成功阅读一条通知！", context)
        elif to_status == Notification.Status.UNDONE:
            notification.status = Notification.Status.UNDONE
            notification.save()
            succeed("成功设置一条通知为未读！", context)
        elif to_status == Notification.Status.DELETE:
            notification.status = Notification.Status.DELETE
            notification.save()
            succeed("您已成功删除一条通知！", context)
        return context


def notification_create(
        receiver: User,
        sender: User | None,
        typename,
        title: str,
        content: str,
        URL: str | None = None,
        relate_instance=None,
        anonymous_flag=False,
        *,
        to_wechat: bool | dict = False,
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
        to_wechat: bool | dict 仅关键字参数
        - 不要在循环中重复调用以发送，你可能需要看`bulk_notification_create`
        - 在线程锁或原子锁内时，也不要发送
        - 若为字典，视为发送给微信的额外参数，主要是应用和发送等级，参考publish_notification即可

    现在，你应该在不急于等待的时候显式调用publish_notification(s)这两个函数，
        具体选择哪个取决于你创建的通知是一批类似通知还是单个通知
    """
    sender = sender or get_default_sender()
    notification = Notification.objects.create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
        URL=URL,
        relate_instance=relate_instance,
        anonymous_flag=anonymous_flag,
    )
    if to_wechat is True or isinstance(to_wechat, dict):
        if to_wechat is True:
            publish_kws = {}
        else:
            publish_kws = to_wechat
        if anonymous_flag:
            publish_kws['show_source'] = False
        publish_notification(notification, **publish_kws)
    return notification


def get_bulk_identifier(
        sender,
        typename,
        title,
        content,
        URL,
        extra_str=None,
):
    '''
    返回一个由内容确定的批量创建识别码
    encode效率约为1e9/s量级，可以全部加密
    '''
    arg_list = []
    arg_list.append(str(sender))
    arg_list.append(str(typename))
    arg_list.append(str(title))

    arg_list.append(hasher.encode(content if content else ''))
    arg_list.append(hasher.encode(URL if URL else ''))

    if extra_str is not None:
        arg_list.append(extra_str)

    bulk_identifier = hasher.encode(' || '.join(arg_list))
    return bulk_identifier


def bulk_notification_create(
        receivers,
        sender,
        typename,
        title,
        content,
        URL=None,
        relate_instance=None,
        *,
        duplicate_behavior='ok',
        to_wechat: bool | dict = False,
):
    """
    对于一个需要创建通知的事件，请调用该函数创建通知！
        receiver: Iter[user], 对于org 或 nat_person，请自行循环生成
        sender: user, 对于org 或 nat_person，使用object.get获取的 user 对象
        typename: 知晓类 或 处理类
        title: 请在数据表中查找相应事件类型，若找不到，直接创建一个新的choice
        content: 输入通知的内容
        URL: 需要跳转到处理事务的页面

    注意事项：
        to_wechat: bool | dict 仅关键字参数
        - 在线程锁或原子锁内时，不要发送
        - 字典视为发送给微信的额外参数，主要是应用和发送等级，参考publish_notifications即可
        duplicate_behavior: str 仅关键字参数
        - 重复通知的处理行为，可选值包括: ok, fail, success, remove, report, log
        - 除了ok之外，这些值都会进行识别码重复检查，分别代表直接失败/成功/移除重复值/报告/记录
        - 移除重复值也会进行记录
        - 希望这个函数是幂等的

    现在，你应该在不急于等待的时候显式调用publish_notification(s)这两个函数，
        具体选择哪个取决于你创建的通知是一批类似通知还是单个通知
    """

    start_time = datetime.now()
    cur_status = '获取识别码'
    bulk_identifier = None
    try:
        # 暂时仍用随机，未来必须可以反向还原，且同一条通知在相近时间必须生成相同识别码
        # 建议的行为是禁用extra_str
        bulk_identifier = get_bulk_identifier(
            sender=sender, typename=typename, title=title,
            content=content, URL=URL,
            extra_str=str(start_time) + str(random()),
        )
        if duplicate_behavior in ['fail', 'success', 'remove', 'report', 'log']:
            cur_status = '检查已存在通知'
            exist_note = Notification.objects.filter(
                bulk_identifier=bulk_identifier,
                start_time__gt=start_time - timedelta(minutes=5),
            )
            if exist_note.exists():
                if duplicate_behavior == 'fail':
                    return False, bulk_identifier
                if duplicate_behavior == 'success':
                    return True, bulk_identifier

                cur_status = '计算已接收名单'
                exist_userids = exist_note.values_list(
                    'receiver_id', flat=True).distinct()
                receiver_ids = [receiver.id for receiver in receivers]
                received_ids = exist_note.filter(
                    receiver_id__in=receiver_ids).values_list('receiver_id', flat=True).distinct()

                cur_status = '重复处理'

                def _short(values):
                    return f'{values[:3]}等{len(values)}个'

                if duplicate_behavior in ['report', 'log']:
                    log_msg = f'批量创建通知时通知已存在, 识别码为{bulk_identifier}'
                    log_msg += f'：尝试创建{len(receiver_ids)}个，已有{_short(received_ids)}，共存在{len(exist_userids)}个'
                    logger.error(
                        log_msg) if duplicate_behavior == 'report' else logger.warning(log_msg)
                if duplicate_behavior == 'remove':
                    cur_status = '移除已有接收者'
                    received_id_set = set(received_ids)
                    receivers = [receiver for receiver in receivers
                                 if receiver.id not in received_id_set]
                    log_msg = f'批量创建通知时通知已存在, 识别码为{bulk_identifier}'
                    log_msg += f'：已移除{_short(received_ids)}已通知用户，剩余{len(receivers)}个'
                    logger.warning(log_msg)
                    if not receivers:
                        return True, bulk_identifier

        cur_status = '生成通知'
        notifications = [
            Notification(
                receiver=receiver,
                sender=sender,
                typename=typename,
                title=title,
                content=content,
                URL=URL,
                bulk_identifier=bulk_identifier,
                relate_instance=relate_instance,
                # start_time=start_time, # 该参数无效，bulk_create会分批生成并覆盖auto_now的字段
            ) for receiver in receivers
        ]
        # 测试表明bulk以50为batch大小时两次创建间的时差为1ms-10ms左右，未来请做测试
        # 注意：bulk_create会分批生成并覆盖auto_now的字段（因此大于start_time），每一批该字段相同
        # 但一批大小多半不为batch_size，暂未确定具体范围，仅保证不大于
        cur_status = '批量创建通知'
        Notification.objects.bulk_create(notifications, 50)
        # TODO:
        # try:
        #     # 重设bulk_create覆盖的auto_now字段
        #     # 暂时非必要，不加锁，允许失败
        #     cur_status = '更新通知时间'
        #     Notification.objects.filter(
        #         bulk_identifier=bulk_identifier,
        #         start_time__gt=start_time,
        #         ).update(start_time=start_time)
        # except:
        #     logger.exception(f'更新通知创建时间时失败, 识别码为{bulk_identifier}, 创建时间为{start_time}')
        success = True
        if to_wechat is True or isinstance(to_wechat, dict):
            cur_status = '发送微信'
            # TODO:
            # 由于识别码将不再是批量创建的唯一值，未来发送微信需要增加参数
            # 当前进度：和原先保持一致，通知重复处理有效，但如果部分已收到通知，其微信会收到多次
            # 可能的实现：增加receiver_ids限制，或者增加start_time精确值（需要保证start_time）
            # 思路1：bulk_create不分批，创建时间统一但与start_time变量不同，无法反向还原
            # 思路2：保证update有效且范围精确，上文中注释了一个不精确的update
            # 思路3：放弃精确，发送所有start_time之后创建的预约
            # 思路4：限制receiver，但定时任务重复触发仍会多次发送
            filter_kws = {
                "bulk_identifier": bulk_identifier,
                # "start_time": start_time,
                # "start_time__gte": start_time,
                # "receiver_id__in": [receiver.id for receiver in receivers],
            }
            if to_wechat is True:
                publish_kws = {}
            else:
                publish_kws = to_wechat
            success = publish_notifications(
                filter_kws=filter_kws, **publish_kws)
    except Exception as e:
        success = False
        logger.exception(f'在{cur_status}时发生错误：识别码为{bulk_identifier}')
    return success, bulk_identifier


# 对一个已经完成的申请, 构建相关的通知和对应的微信消息, 将有关的事务设为已完成
# 如果有错误，则不应该是用户的问题，需要发送到管理员处解决
# 用于报销的通知
# TODO: Reuse
@logger.secure_func(raise_exc=True, exc_type=DeprecationWarning)
def make_notification(application, request, content, receiver):
    # 考虑不同post_type的信息发送行为
    post_type = request.POST.get("post_type")
    feasible_post = ["new_submit", "modify_submit",
                     "cancel_submit", "accept_submit", "refuse_submit"]

    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    URL = {
        'modifyposition': f'/modifyPosition/?pos_id={application.id}',
        'neworganization': f'/modifyOrganization/?org_id={application.id}',
    }
    typename = Notification.Type.NEEDDO if post_type == 'new_submit' else Notification.Type.NEEDREAD
    title = Notification.Title.VERIFY_INFORM if post_type != 'accept_submit' else Notification.Title.POSITION_INFORM

    relate_instance = application if post_type == 'new_submit' else None
    level = (WechatMessageLevel.IMPORTANT
             if post_type != 'cancel_submit'
             else WechatMessageLevel.INFO)
    # TODO cancel是否要发送notification？是否发送微信？

    # 正式创建notification
    notification_create(
        receiver=receiver,
        sender=request.user,
        typename=typename,
        title=title,
        content=content[post_type],
        URL=URL[application.typename],
        relate_instance=relate_instance,
        to_wechat=dict(app=WechatApp.AUDIT, level=level),
    )
    # 对于处理类通知的完成(done)，修改状态
    # 这里的逻辑保证：所有的处理类通知的生命周期必须从“成员发起”开始，从“取消”“通过”“拒绝”结束。
    if feasible_post.index(post_type) >= 2:
        notification_status_change(
            application.relate_notifications.get(
                status=Notification.Status.UNDONE).id,
            Notification.Status.DONE
        )


@logger.secure_func(raise_exc=True)
def notification2Display(notifications: QuerySet[Notification]) -> List[dict]:
    """
    将通知转化为方便前端显示的形式

    :param notifications: 通知的查询集
    :type notifications: QuerySet[Notification]
    :return: 通知的列表，其中每一项是一个包含通知具体信息的字典
    :rtype: List[dict]
    """
    notifications.select_related("sender")

    displays = []
    for notification in notifications:
        note_display = {}

        # id
        note_display["id"] = notification.id

        # 时间
        note_display["start_time"] = notification.start_time.strftime(
            "%Y-%m-%d %H:%M")
        if notification.finish_time is not None:
            note_display["finish_time"] = notification.finish_time.strftime(
                "%Y-%m-%d %H:%M")

        # 留言
        note_display["content"] = notification.content

        # 状态
        note_display["status"] = notification.get_status_display()
        note_display["URL"] = notification.URL
        note_display["type"] = notification.get_typename_display()
        note_display["title"] = notification.get_title_display()

        note_display["sender"] = (notification.sender.name if
                                  not notification.anonymous_flag else "匿名者")
        displays.append(note_display)
    return displays
