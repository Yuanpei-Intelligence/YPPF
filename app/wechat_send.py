'''
wechat_send.py

集合了需要发送到微信的函数

调用提示
    base开头的函数是基础函数，通常作为定时任务，无返回值，但可能打印报错信息
    其他函数可以假设是异步IO，参数符合条件时不抛出异常
    由于异步假设，函数只返回尝试状态，即是否设置了定时任务，不保证成功发送
'''
import requests
import json

# 设置
from django.conf import settings
from boottest import local_dict

# 模型与加密模型
from app.models import NaturalPerson, Organization, Activity, Notification, Position
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

# 日期与定时任务
from datetime import datetime, timedelta

# 获取对象等操作
from app.utils import get_person_or_org
from app import log

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
        from app.scheduler import scheduler
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
if WECHAT_URL[-1:] == "/" and WECHAT_URL[-2:] != "//":
    WECHAT_URL = WECHAT_URL[:-1]  # 去除尾部的/
INVITE_URL = WECHAT_URL + '/invite_user'
wechat_coder = MySHA256Hasher(local_dict["hash"]["wechat"])

# 发送应用设置
UNBLOCK_APPS = set()    # 不要求接收等级的应用
try:
    UNBLOCK_APPS = set(local_dict["config"]["wechat_send"]["unblock_apps"])
except:
    pass
APP2URL = {}    # 应用名到域名的转换，可以是相对地址，也可以是绝对地址
try:
    APP2URL = dict(local_dict["config"]["wechat_send"]["app2url"])
    APP2URL.setdefault('default', '')
except:
    APP2URL = {'default': ''}


# 一批发送的最大数量
SEND_LIMIT = 500  # 上限1000
SEND_BATCH = 500
try:
    SEND_LIMIT = min(1000, int(local_dict["thresholds"]["wechat_send_number"]))
except:
    pass
try:
    SEND_BATCH = min(1000, int(local_dict["thresholds"]["wechat_send_batch"]))
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

class WechatMessageLevel:
    '''
    永远开放：DEFAULT INFO IMPORTANT
    常规上限是1000
    '''
    DEFAULT = None
    DEBUG = -1000
    # ERROR = -100
    INFO = 0
    # NORMAL = 200
    IMPORTANT = 500
    # FATAL = 1000
    # NOREJECT = 1001

class WechatApp:
    '''
    永远开放：DEFAULT NORMAL _*
    注意DEFAULT是指本系统设定的默认窗口
    NORMAL则是发送系统的默认窗口

    请先判断是否符合接受者条件，再判断消息类型
    如果符合接受者条件，请务必显式指定发送的应用，默认值不能判断接受者的范围
    一般建议外部推广也要显示指定应用
    '''
    DEFAULT = None
    # 以接受者
    TO_SUBSCRIBER = 'promote'   # 一切订阅内容都是推广
    TO_PARTICIPANT = 'message'  # 参与者是内部群体
    TO_MEMBER = 'message'       # 发送给成员的是内部消息
    # 以消息类型
    # 状态变更请以接受者为准
    NORMAL = 'default'          # 常规通知，默认窗口即可
    PROMOTION = 'promote'       # 推广消息当然是推广
    TERMINATE = 'message'       # 终止应该发给内部成员
    AUDIT = 'message'           # 审核是重要通知
    TRANSFER = 'message'        # 转账需要通知
    # 固有应用名
    _PROMOTE = 'promote'
    _MESSAGE = 'message'

class WechatDefault:
    '''定义微信发送的默认行为'''
    def get_level(typename, instance=None):
        if typename == 'notification':
            if( instance is not None and
                instance.typename == Notification.Type.NEEDDO):
                # 处理类通知默认等级较高
                return WechatMessageLevel.IMPORTANT
            return WechatMessageLevel.INFO
        else:
            return WechatMessageLevel.INFO

    def get_app(typename, instance=None):
        if typename == 'activity':
            return WechatApp._PROMOTE
        elif typename == 'notification':
            if( instance is not None and
                instance.title == Notification.Title.ACTIVITY_INFORM):
                return WechatApp._PROMOTE
            return WechatApp._MESSAGE
        else:
            return WechatApp.NORMAL


def app2absolute_url(app):
    '''default必须被定义 这里放宽了'''
    url = APP2URL.get(app)
    if url is None:
        url = APP2URL.get('default', '')
    if not url.startswith('http'):
        if not url:
            url = WECHAT_URL
        else:
            url = WECHAT_URL + '/' + url.lstrip('/')
    return url


def base_send_wechat(users, message, app='default',
                     card=True, url=None, btntxt=None, default=True):
    """底层实现发送到微信，是为了方便设置定时任务"""
    post_url = app2absolute_url(app)

    if RECEIVER_SET is not None:
        users = sorted((set(users) & RECEIVER_SET) - BLACKLIST_SET)
    elif BLACKLIST_SET is not None and BLACKLIST_SET:
        users = sorted(set(users) - BLACKLIST_SET)
    else:
        users = sorted(users)
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
        response = requests.post(post_url, post_data, timeout=TIMEOUT)
        response = response.json()
        if response["status"] == 200:           # 全部发送成功
            return
        elif response["data"].get("detail"):    # 部分发送失败
            errinfos = response["data"]["detail"]
            failed = [x[0] for x in errinfos]
            errmsg = errinfos[0][1]             # 失败原因基本相同，取一个即可
        elif response["data"].get("errMsg"):
            errmsg = response["data"]["errMsg"] # 参数等其他传入格式问题
        # users = failed                        # 如果允许重发，则向失败用户重发
        raise OSError("企业微信发送不完全成功")
    except:
        # print(f"第{i+1}次尝试")
        print(f"向企业微信发送失败：失败用户：{failed[:3]}等{len(failed)}人，主要失败原因：{errmsg}")


def send_wechat(
    users,
    message,
    app='default',
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
    - app: 标识应用名的字符串，可以直接使用WechatApp的宏
    - card: 发送文本卡片，建议message长度小于120时开启
    - url: 文本卡片的链接
    - btntxt: 文本卡片的提示短语，不超过4个字
    - default: 填充默认值
    - 仅关键字参数
    - multithread: 不堵塞线程
    - check_duplicate: 检查重复值
    """
    if check_duplicate:
        users = sorted(set(users))
    total_ct = len(users)
    for i in range(0, total_ct, SEND_BATCH):
        userids = users[i : i + SEND_BATCH]  # 一次最多接受1000个
        args = (userids, message, app)
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


@log.except_captured(False, record_args=True, source='wechat_send[publish_notification]')
def publish_notification(notification_or_id,
                        app=None, level=None):
    """
    根据单个通知或id（实际是主键）向通知的receiver发送
    别创建了好多通知然后循环调用这个，批量发送用publish_notifications
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
        app = WechatDefault.get_app('notification', notification)
    check_block = app not in UNBLOCK_APPS
    sender = get_person_or_org(notification.sender)  # 也可能是小组
    url = notification.URL
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = THIS_URL + url

    if len(notification.content) < 120:  # 卡片类型消息最多显示256字节
        kws = {"card": True}  # 因留白等原因，内容120字左右就超出了
        message = "\n".join(
            (
                notification.get_title_display(),
                f"发送者：{str(sender)}",
                "通知内容：",
                notification.content,
            )
        )
        if url:
            kws["url"] = url
            kws["btntxt"] = "查看详情"
    else:  # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join(
            (
                notification.get_title_display(),
                "",
                "发送者：",
                f"{str(sender)}",
                "通知内容：",
                notification.content,
            )
        )
        if url:
            message += f'\n\n<a href="{url}">阅读原文</a>'
        else:
            message += f'\n\n<a href="{DEFAULT_URL}">查看详情</a>'
    receiver = get_person_or_org(notification.receiver)
    if check_block and (level is None or level == WechatMessageLevel.DEFAULT):
        # 考虑屏蔽时，获得默认行为的消息等级
        level = WechatDefault.get_level('notification', notification)
    if isinstance(receiver, NaturalPerson):
        # 如果该应用检查是否拒收，小于接受者的最低接收等级时被拒收
        if check_block and level < receiver.wechat_receive_level:
            return True
        wechat_receivers = [notification.receiver.username]  # user.username是id
    else:  # 小组
        # 转发小组消息给其负责人
        message += f'\n消息来源：{str(receiver)}，请切换到该小组账号进行操作。'
        wechat_receivers = Position.objects.activated().filter(
            org=receiver, is_admin=True)
        if check_block:
            wechat_receivers = wechat_receivers.filter(
                person__wechat_receive_level__lte=level)    # 不小于接收等级
        if not wechat_receivers:    # 没有人接收
            return True
        wechat_receivers = list(wechat_receivers.values_list(
            "person__person_id__username", flat=True
            ))

    send_wechat(wechat_receivers, message, app, **kws)
    return True


@log.except_captured(False, record_args=True, source='wechat_send[publish_notifications]')
def publish_notifications(
    notifications_or_ids=None, filter_kws=None, exclude_kws=None,
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

    sender = get_person_or_org(sender)  # 可能是小组或个人
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = THIS_URL + url

    if len(content) < 120:  # 卡片类型消息最多显示256字节
        kws = {"card": True}  # 因留白等原因，内容120字左右就超出了
        message = "\n".join(
            (
                latest_notification.get_title_display(),
                f"发送者：{str(sender)}",
                "通知内容：",
                content,
            )
        )
        if url:
            kws["url"] = url
            kws["btntxt"] = "查看详情"
    else:  # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join(
            (
                latest_notification.get_title_display(),
                "",
                "发送者：",
                f"{str(sender)}",
                "通知内容：",
                content,
            )
        )
        if url:
            message += f'\n\n<a href="{url}">阅读原文</a>'
        else:
            message += f'\n\n<a href="{DEFAULT_URL}">查看详情</a>'

    # 获得发送应用和消息发送等级
    if app is None or app == WechatApp.DEFAULT:
        app = WechatDefault.get_app('notification', latest_notification)
    check_block = app not in UNBLOCK_APPS
    if check_block and (level is None or level == WechatMessageLevel.DEFAULT): 
        level = WechatDefault.get_level('notification', latest_notification)

    # 获取接收者列表，小组的接收者为其负责人，去重
    receiver_ids = notifications.values_list("receiver_id", flat=True)
    person_receivers = NaturalPerson.objects.filter(person_id__in=receiver_ids)
    # 如果检查是否屏蔽，仅发送给最小接收等级不大于发送等级的人
    if check_block:
        person_receivers = person_receivers.filter(wechat_receive_level__lte=level)
    wechat_receivers = list(
        person_receivers.values_list("person_id__username", flat=True)
    )
    receiver_set = set(wechat_receivers)

    # 接下来是发送给小组的部分
    org_receivers = Organization.objects.filter(organization_id__in=receiver_ids)
    activate_positions = Position.objects.activated()
    for org in org_receivers:
        managers = activate_positions.filter(
            org=org, is_admin=True)
        if check_block:    # 屏蔽时，不小于接收等级
            managers = managers.filter(person__wechat_receive_level__lte=level)
        managers = managers.values_list("person__person_id__username", flat=True)
        managers = [manager for manager in managers if not manager in receiver_set]
        wechat_receivers.extend(managers)
        receiver_set.update(managers)
    if not wechat_receivers:    # 可能都不接收此等级的消息
        return True

    send_wechat(wechat_receivers, message, app, **kws)
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


def send_wechat_captcha(stu_id: str or int, captcha: str, url='/forgetpw/'):
    users = (stu_id, )
    kws = {"card": True}
    if url and url[0] == "/":  # 相对路径变为绝对路径
        url = THIS_URL + url
    message = (
                "YPPF登录验证\n"
                "您的账号正在进行企业微信验证\n本次请求的验证码为："
                f"<div class=\"highlight\">{captcha}</div>"
                f"发送时间：{datetime.now().strftime('%m月%d日 %H:%M:%S')}"
            )
    if url:
        kws["url"] = url
        kws["btntxt"] = "登录"
    send_wechat(users, message, **kws)


def base_invite(stu_id:str or int, retry_times=None):
    if retry_times is None:
        retry_times = 1
    try:
        stu_id = str(stu_id)
        retry_times = int(retry_times)
    except:
        print(f"发送邀请的参数异常：学号为{stu_id}，重试次数为{retry_times}")

    post_data = {
        "user": stu_id,
        "secret": wechat_coder.encode(stu_id),
    }
    post_data = json.dumps(post_data)
    for i in range(retry_times):
        end = False
        try:
            errmsg = "连接api失败"
            response = requests.post(INVITE_URL, post_data, timeout=TIMEOUT)
            response = response.json()
            if response["status"] == 200:  # 全部发送成功
                return
            elif response["data"].get("detail"):    # 发送失败
                errmsg = response["data"]["detail"]
            elif response["data"].get("errMsg"):    # 参数等其他传入格式问题
                errmsg = response["data"]["errMsg"]
                end = True
            raise OSError("企业微信发送不完全成功")
        except:
            print(f"第{i+1}次向企业微信发送邀请失败：用户：{stu_id}，原因：{errmsg}")
            if end:
                return


def invite(stu_id: str or int, retry_times=3, *, multithread=True):
    args = (stu_id, )
    kwargs = {'retry_times': retry_times}
    if USE_MULTITHREAD and multithread:
        # 多线程
        scheduler.add_job(
            base_invite,
            "date",
            args=args,
            kwargs=kwargs,
            next_run_time=datetime.now() + timedelta(seconds=5),
        )
    else:
        base_invite(*args, **kwargs)  # 不使用定时任务请改为这句
