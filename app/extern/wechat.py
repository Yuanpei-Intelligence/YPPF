'''
wechat.py

集合了本应用需要发送到微信的函数

调用提示
    函数可以假设是异步IO，参数符合条件时不抛出异常
    由于异步假设，函数只返回尝试状态，即是否设置了定时任务，不保证成功发送
'''
from datetime import timedelta

from extern.wechat import send_wechat, DEFAULT_URL
from app.extern.config import (
    notification_wechat_config as CONFIG,
    Levels as WechatMessageLevel,
    Apps as WechatApp,
)
from app.models import NaturalPerson, Organization, Activity, Notification, Position
from app.utils import get_person_or_org
from utils.http.utils import build_full_url
from app import log


__all__ = [
    'WechatApp', 'WechatMessageLevel',
    'publish_notification', 'publish_notifications',
]


def app2path(app: str) -> str:
    '''将应用名转换为路径，可能是绝对路径'''
    url = CONFIG.app2url.get(app)
    if url is None:
        url = CONFIG.app2url.get('default', '')
    return url


def _get_default_level(typename, instance=None) -> int:
    if typename == 'notification':
        if (instance is not None and
            instance.typename == Notification.Type.NEEDDO):
            # 处理类通知默认等级较高
            return WechatMessageLevel.IMPORTANT
        return WechatMessageLevel.INFO
    else:
        return WechatMessageLevel.INFO


def _get_default_app(typename, instance=None) -> str:
    if typename == 'activity':
        return WechatApp._PROMOTE
    elif typename == 'notification':
        if (instance is not None and
            instance.title == Notification.Title.ACTIVITY_INFORM):
            return WechatApp._PROMOTE
        return WechatApp._MESSAGE
    else:
        return WechatApp.NORMAL


def can_send(person, level=None):
    '''获取个人接收人是否接收'''
    if level is not None and level < person.wechat_receive_level:
        return False
    return True


def org2receivers(org, level=None, force=True):
    '''获取组织接收人的学号列表'''
    managers = Position.objects.activated().filter(org=org, is_admin=True)
    # 提供等级时，不小于接收等级
    if level is not None:
        receivers = managers.filter(person__wechat_receive_level__lte=level)
        if not receivers.exists() and force:
            receivers = managers.filter(pos=0)
        managers = receivers
    return list(managers.values_list("person__person_id__username", flat=True))


def user2receivers(user, level=None, get_obj=False):
    '''供发布级YPPF接口调用的函数，获取接收人的学号列表，以及可选的原始对象'''
    receiver = get_person_or_org(user)
    if isinstance(receiver, NaturalPerson):
        wechat_receivers = [user.username] if can_send(receiver, level) else []
    else:
        wechat_receivers = org2receivers(receiver, level)
    if get_obj:
        return wechat_receivers, receiver
    return wechat_receivers


def get_person_receivers(all_receiver_ids, level=None):
    '''获取接收的个人的学号列表'''
    receivers = NaturalPerson.objects.activated().filter(
        person_id__in=all_receiver_ids)
    # 提供等级时，不小于接收等级
    if level is not None:
        receivers = receivers.filter(wechat_receive_level__lte=level)
    receivers = list(receivers.values_list("person_id__username", flat=True))
    return receivers


@log.except_captured(False, record_args=True, source='wechat_send[publish_notification]')
def publish_notification(notification_or_id,
                        show_source=True,
                        app=None, level=None):
    """
    根据单个通知或id（实际是主键）向通知的receiver发送
    别创建了好多通知然后循环调用这个，批量发送用publish_notifications
    - show_source: bool, 显示消息来源 默认显示
    - app: str | WechatApp宏, 确定发送的应用 请推广类消息务必注意
    - level: int | WechatMessageLevel宏, 用于筛选用户 推广类消息可以不填
    """
    try:
        if isinstance(notification_or_id, Notification):
            notification = notification_or_id
        else:
            notification = Notification.objects.get(pk=notification_or_id)
    except:
        raise ValueError("未找到该id的通知")
    if app is None or app == WechatApp.DEFAULT:
        app = _get_default_app('notification', notification)
    check_block = app not in CONFIG.unblock_apps
    url = notification.URL
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = build_full_url(url)

    messages = [notification.get_title_display()]
    if len(notification.content) < 120:
        # 卡片类型消息最多显示256字节
        # 因留白等原因，内容120字左右就超出了
        kws = {"card": True}
        if show_source:
            sender = get_person_or_org(notification.sender)
            # 通知内容暂时也一起去除了
            messages += [f'发送者：{str(sender)}', '通知内容：']
        messages += [notification.content]
        if url:
            kws["url"] = url
            kws["btntxt"] = "查看详情"
    else:
        # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        messages.append('')
        if show_source:
            sender = get_person_or_org(notification.sender)
            # 通知内容暂时也一起去除了
            messages += ['发送者：' + f'{str(sender)}', '通知内容：']
        messages += [notification.content]
        if url:
            messages += ['', f'<a href="{url}">阅读原文</a>']
        else:
            messages += ['', f'<a href="{DEFAULT_URL}">查看详情</a>']

    # 获取完整消息
    message = '\n'.join(messages)

    if check_block and (level is None or level == WechatMessageLevel.DEFAULT):
        # 考虑屏蔽时，获得默认行为的消息等级
        level = _get_default_level('notification', notification)
    elif not check_block:
        # 不屏蔽时，消息等级设置为空
        level = None
    # 获取接受者列表
    wechat_receivers, receiver = user2receivers(notification.receiver, level,
                                                get_obj=True)
    if isinstance(receiver, Organization):  # 小组
        # 转发小组消息给其负责人
        message += f'\n消息来源：{str(receiver)}，请切换到该小组账号进行操作。'
    if not wechat_receivers:    # 没有人接收
        return True

    send_wechat(wechat_receivers, message, app2path(app), **kws)
    return True


@log.except_captured(False, record_args=True, source='wechat_send[publish_notifications]')
def publish_notifications(
    notifications_or_ids=None, filter_kws=None, exclude_kws=None,
    show_source=True,
    app=None, level=None,
    *, check=True
):
    """
    批量发送通知，选取筛选后范围内所有与最新通知发送者等相同、且内容结尾一致的通知
    如果能保证这些通知全都一致，可以要求不检查

    Argument
    --------
    - notifications_or_ids: QuerySet | List or Tuple[notification with id] |
        Iter[id] | None, 通知基本范围, 别问参数类型为什么这么奇怪，问就是django不统一
    - filter_kws: dict | None, 这些参数将被直接传递给filter函数
    - exclude_kws: dict | None, 这些参数将被直接传递给exclude函数
    - 以上参数不能都为空
    
    - show_source: bool, 显示消息来源 默认显示
    - app: str | WechatApp宏, 确定发送的应用 请推广类消息务必注意
    - level: int | WechatMessageLevel宏, 用于筛选用户 推广类消息可以不填

    Keyword-Only
    ------------
    - check: bool, default=True, 是否检查最终筛选结果的相关性

    Returns
    -------
    - success: bool, 是否尝试了发送，出错时返回False
    """
    if notifications_or_ids is None and filter_kws is None and exclude_kws is None:
        raise ValueError("必须至少传入一个有效参数才能发布通知到微信！")
    try:
        notifications = Notification.objects.all()
        if notifications_or_ids is not None:
            if (isinstance(notifications_or_ids, (list, tuple))
                and notifications_or_ids
                and isinstance(notifications_or_ids[0], Notification)
                ):
                notifications_or_ids = [n.id for n in notifications_or_ids]
            notifications = notifications.filter(id__in=notifications_or_ids)
        if filter_kws is not None:
            notifications = notifications.filter(**filter_kws)
        if exclude_kws is not None:
            notifications = notifications.exclude(**exclude_kws)
        notifications = notifications.order_by("-start_time")
    except:
        raise ValueError("必须至少传入一个有效参数才能发布通知到微信！")

    total_ct = len(notifications)
    if total_ct == 0:
        return True
    try:
        latest_notification = notifications[0]
        sender = latest_notification.sender
        typename = latest_notification.typename
        title = latest_notification.title
        content = latest_notification.content
        content_start = content[:10]
        content_end = content[-10:]
        url = latest_notification.URL
        if check:
            send_time = latest_notification.start_time
            before_5min = send_time - timedelta(minutes=5)  # 最多差5分钟
            notifications = notifications.filter(
                sender=sender,
                typename=typename,
                title=title,
                start_time__gte=before_5min,
                content__startswith=content_start,
                content__endswith=content_end,
                URL=url,
            )
    except:
        raise Exception("检查失败，发生了未知错误，这里不该发生异常")

    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = build_full_url(url)

    messages = [latest_notification.get_title_display()]
    if len(latest_notification.content) < 120:
        # 卡片类型消息最多显示256字节
        # 因留白等原因，内容120字左右就超出了
        kws = {"card": True}
        if show_source:
            sender = get_person_or_org(latest_notification.sender)
            # 通知内容暂时也一起去除了
            messages += [f'发送者：{str(sender)}', '通知内容：']
        messages += [latest_notification.content]
        if url:
            kws["url"] = url
            kws["btntxt"] = "查看详情"
    else:
        # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        messages.append('')
        if show_source:
            sender = get_person_or_org(latest_notification.sender)
            # 通知内容暂时也一起去除了
            messages += ['发送者：' + f'{str(sender)}', '通知内容：']
        messages += [latest_notification.content]
        if url:
            messages += ['', f'<a href="{url}">阅读原文</a>']
        else:
            messages += ['', f'<a href="{DEFAULT_URL}">查看详情</a>']

    # 获取完整消息
    message = '\n'.join(messages)

    # 获得发送应用和消息发送等级
    if app is None or app == WechatApp.DEFAULT:
        app = _get_default_app('notification', latest_notification)
    check_block = app not in CONFIG.unblock_apps
    if check_block and (level is None or level == WechatMessageLevel.DEFAULT):
        level = _get_default_level('notification', latest_notification)
    if not check_block:
        level = None

    # 获取接收者列表，小组的接收者为其负责人，去重
    receiver_ids = notifications.values_list("receiver_id", flat=True)
    person_receivers = get_person_receivers(receiver_ids, level)
    wechat_receivers = person_receivers
    receiver_set = set(wechat_receivers)

    # 接下来是发送给小组的部分
    org_receivers = Organization.objects.activated().filter(
        organization_id__in=receiver_ids)
    for org in org_receivers:
        managers = [
            manager for manager in org2receivers(org, level, force=False)
            if manager not in receiver_set
        ]
        wechat_receivers.extend(managers)
        receiver_set.update(managers)
    if not wechat_receivers:    # 可能都不接收此等级的消息
        return True

    send_wechat(wechat_receivers, message, app2path(app), **kws)
    return True


def publish_activity(activity_or_id):
    """根据活动或id（实际是主键）向所有订阅该小组信息的在校学生发送"""
    raise NotImplementedError('该函数已废弃')
    try:
        if isinstance(activity_or_id, Activity):
            activity = activity_or_id
        else:
            activity = Activity.objects.get(pk=activity_or_id)
    except:
        print(f"未找到id为{activity_or_id}的活动")
        return False

    org = activity.organization_id
    subscribers = NaturalPerson.objects.activated().exclude(
        id__in=org.unsubscribers.all()
    )  # flat=True时必须只有一个键
    subscribers = list(subscribers.values_list("person_id__username", flat=True))
    num = len(subscribers)
    start, finish = activity.start, activity.finish
    timeformat = "%Y-%m-%d %H:%M"  # 显示具体年份
    start = start.strftime(timeformat)
    finish = finish.strftime(timeformat)
    content = (
        activity.introduction if not hasattr(activity, "content") else activity.content
    )  # 模型发生了改变
    url = activity.URL
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = build_full_url(url)

    if len(content) < 120:  # 卡片类型消息最多显示256字节
        kws = {"card": True}  # 因留白等原因，内容120字左右就超出了
        message = "\n".join(
            (
                activity.title,
                f"组织者：{activity.organization_id.oname}",
                f"活动时间：{start}-{finish}",
                "活动内容：",
                content,
                "查看详情",
            )
        )
        if url:
            kws["url"] = url
            kws["btntxt"] = "阅读原文"
    else:  # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join(
            (
                activity.title,
                "",
                "组织者：",
                f"{activity.organization_id.oname}",
                "活动时间：",
                f"{start}-{finish}",
                "活动简介：",
                content,
            )
        )
        if url:
            message += f'\n\n<a href="{url}">阅读原文</a>'
        else:
            message += f'\n\n<a href="{DEFAULT_URL}">查看详情</a>'
    send_wechat(subscribers, message, **kws)
    return True
