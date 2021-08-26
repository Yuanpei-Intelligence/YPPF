import requests
import json

# 设置
from django.conf import settings
from boottest import local_dict

# 模型与加密模型
from app.models import NaturalPerson, Organization, Activity, Notification, Participant
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

# 日期与定时任务
from datetime import datetime, timedelta

# 获取对象等操作
from app.utils import get_person_or_org

# 全局设置
# 是否启用定时任务，请最好仅在服务器启用，如果不启用，后面的多个设置也会随之变化
USE_SCHEDULER = True
try:
    USE_SCHEDULER = bool(local_dict["config"]["wechat_send"]["use_scheduler"])
except:
    pass
# 是否多线程发送，必须启用scheduler，如果启用则发送时无需等待
USE_MULTITHREAD = True if USE_SCHEDULER else False
# 决定单次连接的超时时间，响应时间一般为1s或12s（偶尔），建议考虑前端等待时间放弃12s
TIMEOUT = 15 if USE_MULTITHREAD else 5 or 3.05 or 12 or 15
# 订阅系统的发送量非常大，不建议重发，因为发送失败之后短时间内重发大概率也会失败
# 如果未来实现重发，应在base_send_wechat中定义作为参数读入，现在提供了几句简单的代码
RETRY = False

if USE_SCHEDULER:
    try:
        from app.scheduler_func import scheduler
    except:
        from apscheduler.schedulers.background import BackgroundScheduler
        from django_apscheduler.jobstores import DjangoJobStore

        scheduler = BackgroundScheduler()
        scheduler.add_jobstore(DjangoJobStore(), "default")
        scheduler.start()

# 全局变量 用来发送和确认默认的导航网址
DEFAULT_URL = settings.LOGIN_URL
THIS_URL = settings.LOGIN_URL  # 增加默认url前缀
if THIS_URL[-1:] == "/" and THIS_URL[-2:] != "//":
    THIS_URL = THIS_URL[:-1]  # 去除尾部的/
WECHAT_URL = local_dict["url"]["wechat_url"]
wechat_coder = MySHA256Hasher(local_dict["hash"]["wechat"])

# 一批发送的最大数量
SEND_LIMIT = 500  # 上限1000
SEND_BATCH = 500
try:
    SEND_LIMIT = min(1000, int(local_dict["threholds"]["wechat_send_number"]))
except:
    pass
try:
    SEND_BATCH = min(1000, int(local_dict["threholds"]["wechat_send_batch"]))
except:
    pass

# 限制接收范围
RECEIVER_SET = None  # 可接收范围，默认全体
BLACKLIST_SET = set()  # 黑名单，默认没有，可以用来排除元培学院等特殊用户
try:
    r_range = local_dict["config"]["wechat_send"]["receivers"]
    RECEIVER_SET = set(map(str, r_range)) if r_range is not None else None
except:
    pass
try:
    BLACKLIST_SET = set(map(str, local_dict["config"]["wechat_send"]["blacklist"]))
except:
    pass


def base_send_wechat(users, message, card=True, url=None, btntxt=None, default=True):
    """底层实现发送到微信，是为了方便设置定时任务"""
    if RECEIVER_SET is not None:
        users = list((set(users) & RECEIVER_SET) - BLACKLIST_SET)
    else:
        users = list(set(users) - BLACKLIST_SET)
    user_num = len(users)
    if user_num == 0:
        print("没有合法的用户")
        return
    if user_num > SEND_LIMIT:
        print("用户列表过长,", f"{users[SEND_LIMIT: SEND_LIMIT+3]}等{user_num-SEND_LIMIT}人被舍去")
        users = users[:SEND_LIMIT]
    post_data = {
        "touser": users,
        "content": message,
        "toall": True,
        "secret": wechat_coder.encode(message),
    }
    if card:
        if url is not None and url[:1] in ["", "/"]:  # 空或者相对路径，变为绝对路径
            url = THIS_URL + url
        post_data["card"] = True
        if default:
            post_data["url"] = url if url is not None else DEFAULT_URL
            post_data["btntxt"] = btntxt if btntxt is not None else "详情"
        else:
            if url is not None:
                post_data["url"] = url
            if btntxt is not None:
                post_data["btntxt"] = btntxt
    post_data = json.dumps(post_data)
    # if not RETRY or not retry_times:
    #     retry_times = 1
    # for i in range(retry_times):
    try:
        failed = users
        errmsg = "连接api失败"
        response = requests.post(WECHAT_URL, post_data, timeout=TIMEOUT)
        response = response.json()
        if response["status"] == 200:  # 全部发送成功
            return
        elif response["data"].get("detail"):  # 部分发送失败
            errinfos = response["data"]["detail"]
            failed = [x[0] for x in errinfos]
            errmsg = errinfos[0][1]  # 失败原因基本相同，取一个即可
        elif response["data"].get("errMsg"):
            errmsg = response["data"]["errMsg"]  # 参数等其他传入格式问题
        # users = failed                                    # 如果允许重发，则向失败用户重发
        raise OSError("企业微信发送不完全成功")
    except:
        # print(f"第{i+1}次尝试")
        print(f"向企业微信发送失败：失败用户：{failed[:3]}等{len(failed)}人，主要失败原因：{errmsg}")


def send_wechat(
    users,
    message,
    card=True,
    url=None,
    btntxt=None,
    default=True,
    *,
    multithread=True,
    check_duplicate=False,
):
    """
    附带了去重、多线程和batch的发送，默认不去重；注意这个函数不应被直接调用

    参数(部分)
    --------
    - users: 随机访问容器，如果检查重复，则可以是任何可迭代对象
    - message: 一段文字，第一个\n被视为标题和内容的分隔符
    - card: 发送文本卡片，建议message长度小于120时开启
    - url: 文本卡片的链接
    - btntxt: 文本卡片的提示短语，不超过4个字
    - default: 填充默认值
    - multithread: 不堵塞线程
    - check_duplicate: 检查重复值
    """
    if check_duplicate:
        users = sorted(set(users))
    total_ct = len(users)
    for i in range(0, total_ct, SEND_BATCH):
        userids = users[i : i + SEND_BATCH]  # 一次最多接受1000个
        args = (userids, message)
        kws = {"card": card, "url": url, "btntxt": btntxt, "default": default}
        if USE_MULTITHREAD and multithread:
            # 多线程
            scheduler.add_job(
                base_send_wechat,
                "date",
                args=args,
                kwargs=kws,
                next_run_time=datetime.now() + timedelta(seconds=5 + round(i / 50)),
            )
        else:
            base_send_wechat(*args, **kws)  # 不使用定时任务请改为这句


def publish_notification(notification_or_id):
    """
    根据单个通知或id（实际是主键）向通知的receiver发送
    别创建了好多通知然后循环调用这个，批量发送用publish_notifications
    """
    try:
        if isinstance(notification_or_id, Notification):
            notification = notification_or_id
        else:
            notification = Notification.objects.get(pk=notification_or_id)
    except:
        print(f"未找到id为{notification_or_id}的通知")
        return False
    sender = get_person_or_org(notification.sender)  # 也可能是组织
    send_time = notification.start_time
    timeformat = "%Y年%m月%d日 %H:%M"
    send_time = send_time.strftime(timeformat)

    if len(notification.content) < 120:  # 卡片类型消息最多显示256字节
        kws = {"card": True}  # 因留白等原因，内容120字左右就超出了
        message = "\n".join(
            (
                notification.get_title_display(),
                f"发送者：{str(sender)}",
                f"通知时间：{send_time}",
                "通知内容：",
                notification.content,
                "点击查看详情",
            )
        )
        if notification.URL:
            kws["url"] = notification.URL
            kws["btntxt"] = "阅读原文"
    else:  # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join(
            (
                notification.get_title_display(),
                "",
                "发送者：",
                f"{str(sender)}",
                "通知时间：",
                f"{send_time}",
                "通知内容：",
                notification.content,
            )
        )
        if notification.URL:
            url = notification.URL
            if url[0] == "/":  # 相对路径变为绝对路径
                url = THIS_URL + url
            message += f'\n\n<a href="{url}">阅读原文</a>'
        else:
            message += f'\n\n<a href="{DEFAULT_URL}">点击查看详情</a>'
    receiver = get_person_or_org(notification.receiver)
    if isinstance(receiver, NaturalPerson):
        wechat_receivers = [notification.receiver.username]  # user.username是id
    else:  # 组织
        wechat_receivers = list(
            receiver.position_set.filter(pos=0).values_list(
                "person__person_id__username", flat=True
            )
        )

    send_wechat(wechat_receivers, message, **kws)  # 不使用定时任务请改为这句
    return True


def publish_notifications(
    notifications_or_ids=None, filter_kws=None, exclude_kws=None, *, check=True
):
    """
    批量发送通知，选取筛选后范围内所有与最新通知发送者等相同、且内容结尾一致的通知
    如果能保证这些通知全都一致，可以要求不检查

    Argument
    --------
    - notifications_or_ids: Iter[notification | id] | None, 通知基本范围
    - filter_kws: dict | None, 这些参数将被直接传递给filter函数
    - exclude_kws: dict | None, 这些参数将被直接传递给exclude函数
    - 以上参数不能都为空

    Keyword-Only
    ------------
    - check: bool, default=True, 是否检查最终筛选结果的相关性

    Returns
    -------
    - success: bool, 是否尝试了发送，出错时返回False
    """
    if notifications_or_ids is None and filter_kws is None and exclude_kws is None:
        print("必须至少传入一个有效参数才能发布通知到微信！")
        return False
    try:
        notifications = Notification.objects.all()
        if notifications_or_ids is not None:
            notifications = notifications.filter(id__in=notifications_or_ids)
        if filter_kws is not None:
            notifications = notifications.filter(**filter_kws)
        if exclude_kws is not None:
            notifications = notifications.exclude(**exclude_kws)
        notifications = notifications.order_by("-start_time")
    except:
        print(f"传给publish_notifications的参数错误！")
        return False

    total_ct = len(notifications)
    if total_ct == 0:
        return True
    try:
        latest_notification = notifications[0]
        sender = latest_notification.sender
        typename = latest_notification.typename
        title = latest_notification.title
        send_time = latest_notification.start_time
        content = latest_notification.content
        content_start = content[:10]
        content_end = content[-10:]
        url = latest_notification.URL
        if check:
            notifications = notifications.filter(
                sender=sender,
                typename=typename,
                title=title,
                content__startswith=content_start,
                content__endswith=content_end,
                URL=url,
            )
    except:
        print("检查失败，发生了未知错误，这里不该发生异常")
        return False

    sender = get_person_or_org(sender)  # 可能是组织或个人
    timeformat = "%Y年%m月%d日 %H:%M"
    send_time = send_time.strftime(timeformat)
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = THIS_URL + url

    if len(content) < 120:  # 卡片类型消息最多显示256字节
        kws = {"card": True}  # 因留白等原因，内容120字左右就超出了
        message = "\n".join(
            (
                latest_notification.get_title_display(),
                f"发送者：{str(sender)}",
                f"通知时间：{send_time}",
                "通知内容：",
                content,
                "点击查看详情",
            )
        )
        if url:
            kws["url"] = url
            kws["btntxt"] = "阅读原文"
    else:  # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join(
            (
                latest_notification.get_title_display(),
                "",
                "发送者：",
                f"{str(sender)}",
                "通知时间：",
                f"{send_time}",
                "通知内容：",
                content,
            )
        )
        if url:
            message += f'\n\n<a href="{url}">阅读原文</a>'
        else:
            message += f'\n\n<a href="{DEFAULT_URL}">点击查看详情</a>'

    # 获取接收者列表，组织的接收者为其负责人，去重
    receiver_ids = notifications.values_list("receiver_id", flat=True)
    person_receivers = NaturalPerson.objects.filter(person_id__in=receiver_ids)
    wechat_receivers = list(
        person_receivers.values_list("person_id__username", flat=True)
    )
    receiver_set = set(wechat_receivers)
    org_receivers = Organization.objects.filter(organization_id__in=receiver_ids)
    for org in org_receivers:
        managers = org.position_set.filter(pos=0).values_list(
            "person__person_id__username", flat=True
        )
        managers = [manager for manager in managers if not manager in receiver_set]
        wechat_receivers.extend(managers)
        receiver_set.update(managers)

    send_wechat(wechat_receivers, message, **kws)
    return True


def publish_activity(activity_or_id):
    """根据活动或id（实际是主键）向所有订阅该组织信息的学生发送，可以只发给在校学生"""
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
    if start.year == datetime.now().year and finish.year == datetime.now().year:
        timeformat = "%m月%d日 %H:%M"  # 一般不显示年和秒
    else:
        timeformat = "%Y年%m月%d日 %H:%M"  # 显示具体年份
    start = start.strftime(timeformat)
    finish = finish.strftime(timeformat)
    content = (
        activity.introduction if not hasattr(activity, "content") else activity.content
    )  # 模型发生了改变
    url = activity.URL
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = THIS_URL + url

    if len(content) < 120:  # 卡片类型消息最多显示256字节
        kws = {"card": True}  # 因留白等原因，内容120字左右就超出了
        message = "\n".join(
            (
                activity.title,
                f"组织者：{activity.organization_id.oname}",
                f"活动时间：{start}-{finish}",
                "活动内容：",
                content,
                "点击查看详情",
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
            message += f'\n\n<a href="{DEFAULT_URL}">点击查看详情</a>'
    send_wechat(subscribers, message, **kws)
    return True


def wechat_notify_activity(aid, msg, send_to, url=None):
    activity = Activity.objects.get(id=aid)
    targets = set()
    if send_to == "participants" or send_to == "all":
        participants = Participant.objects.filter(
            activity_id=aid,
            status__in=[
                Participant.AttendStatus.APLLYSUCCESS,
                Participant.AttendStatus.APPLYING,
            ],
        )
        participants = list(participants.values_list("person_id__username", flat=True))
        targets |= set(participants)

    if send_to == "subscribers" or send_to == "all":
        org = activity.organization_id
        subcribers = NaturalPerson.objects.difference(org.unsubsribers)
        subcribers = subcribers.exclude(status=NaturalPerson.GraduateStatus.GRADUATED)
        subcribers = list(subcribers.values_list("person_id__username", flat=True))
        targets |= set(subcribers)

    send_wechat(targets, msg, card=int(len(msg) < 120), url=url, check_duplicate=True)

