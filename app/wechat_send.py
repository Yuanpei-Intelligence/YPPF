import requests
import json

# 设置
from django.conf import settings
from boottest import local_dict

# 模型与加密模型
from app.models import NaturalPerson, Activity, Notification
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher

# 日期与定时任务
from datetime import datetime, timedelta

# 全局设置
# 是否启用定时任务，请最好仅在服务器启用，如果不启用，后面的多个设置也会随之变化
USE_SCHEDULER = True
try: USE_SCHEDULER = bool(local_dict['config']['wechat_send']['use_scheduler'])
except: pass
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
THIS_URL = settings.LOGIN_URL                       # 增加默认url前缀
if THIS_URL[-1:] == '/' and THIS_URL[-2:] != '//':
    THIS_URL = THIS_URL[:-1]                        # 去除尾部的/
WECHAT_URL = local_dict["url"]["wechat_url"]
wechat_coder = MySHA256Hasher(local_dict["hash"]["wechat"])

# 一批发送的最大数量
WECHAT_BUDGET = 500     # 上限1000
ACTIVITY_BUDGET = 500                                  
try: WECHAT_BUDGET = min(1000, int(local_dict['threholds']['wechat_budget']))
except: pass                         
try: ACTIVITY_BUDGET = int(local_dict['threholds']['activity_budget'])
except: pass

# 限制接收范围
RECEIVER_SET = None     # 可接收范围，默认全体
BLACKLIST_SET = set()   # 黑名单，默认没有，可以用来排除元培学院等特殊用户
try: 
    r_range = local_dict['config']['wechat_send']['receivers']
    RECEIVER_SET = set(map(str, r_range)) if r_range is not None else None
except: pass
try: BLACKLIST_SET = set(map(str, local_dict['config']['wechat_send']['blacklist']))
except: pass


def base_send_wechat(users, message, card=True, url=None, btntxt=None, default=True):
    '''底层实现发送到微信，是为了方便设置定时任务'''
    if RECEIVER_SET is not None:
        users = list((set(users) & RECEIVER_SET) - BLACKLIST_SET)
    else:
        users = list(set(users) - BLACKLIST_SET)
    user_num = len(users)
    if user_num == 0:
        print('没有合法的用户')
        return
    if user_num > WECHAT_BUDGET:
        print(
            '用户列表过长,',
            f'{users[WECHAT_BUDGET: WECHAT_BUDGET+3]}等{user_num-WECHAT_BUDGET}人被舍去'
        )
        users = users[:WECHAT_BUDGET]
    post_data = {
        "touser": users,
        "content": message,
        "toall": True,
        "secret": wechat_coder.encode(message)
    }
    if card:
        post_data["card"] = True
        if default:
            post_data["url"] = url if url is not None else DEFAULT_URL
            post_data["btntxt"] = btntxt if btntxt is not None else "详情"
        else:
            if url is not None:
                if url[:1] in ['', '/']:    # 空或者相对路径，变为绝对路径
                    url = THIS_URL + url
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
        if response["status"] == 200:                       # 全部发送成功
            return
        elif response["data"].get("detail"):                # 部分发送失败
            errinfos = response["data"]["detail"]
            failed = [x[0] for x in errinfos]
            errmsg = errinfos[0][1]                         # 失败原因基本相同，取一个即可
        elif response["data"].get("errMsg"):
            errmsg = response["data"]["errMsg"]             # 参数等其他传入格式问题
        # users = failed                                    # 如果允许重发，则向失败用户重发
        raise OSError('企业微信发送不完全成功')
    except:
        # print(f"第{i+1}次尝试")
        print(f"向企业微信发送失败：失败用户：{failed[:3]}等{len(failed)}人，主要失败原因：{errmsg}")


def publish_notification(notification_or_id):
    '''
    根据单个通知或id（实际是主键）向通知的receiver发送
    别创建了好多通知然后循环调用这个，之后会出批量发送的
    '''
    try:
        if isinstance(notification_or_id, Notification):
            notification = notification_or_id
        else:
            notification = Notification.objects.get(pk=notification_or_id)
    except:
        print(f"未找到id为{notification_or_id}的通知")
        return False
    from app.views import get_person_or_org     # 获取名称
    sender = get_person_or_org(notification.sender) # 也可能是组织
    send_time = notification.start_time
    timeformat = "%Y年%m月%d日 %H:%M"   
    send_time = send_time.strftime(timeformat)

    if len(notification.content) < 120:         # 卡片类型消息最多显示256字节
        kws = {"card": True}                    # 因留白等原因，内容120字左右就超出了
        message = "\n".join((
            notification.get_title_display(),
            f"发送者：{str(sender)}",
            f"通知时间：{send_time}",
            "通知内容：",
            notification.content,
            "点击查看详情"
        ))
        if notification.URL:
            kws["url"] = notification.URL
            kws["btntxt"] = "阅读原文"
    else:                                       # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join((
            notification.get_title_display(),
            "",
            "发送者：",
            f"{str(sender)}",
            "通知时间：",
            f"{send_time}",
            "通知内容：",
            notification.content
        ))
        if notification.URL:
            message += f"\n\n<a href=\"{notification.URL}\">阅读原文</a>"
        else:
            message += f"\n\n<a href=\"{DEFAULT_URL}\">点击查看详情</a>"
    receiver = get_person_or_org(notification.receiver)
    if isinstance(receiver, NaturalPerson):
        wechat_receivers = [notification.receiver.username] # user.username是id
    else:   # 组织
        wechat_receivers = list(receiver.position_set.filter(pos=0).
                                values_list("person__person_id__username", flat=True))
        if len(wechat_receivers) == 0:
            return True
    if USE_MULTITHREAD:
        # 多线程
        scheduler.add_job(base_send_wechat, 'date',
                            args=(wechat_receivers, message),
                            kwargs=kws,
                            next_run_time=datetime.now() + timedelta(seconds=5)
                            )
    else:
        base_send_wechat(wechat_receivers,
                            message, **kws) # 不使用定时任务请改为这句
    return True
publish_notification.ENABLE_INSTANCE = True # 标识接收的参数类型


def publish_activity(activity_or_id, only_activated=False):
    '''根据活动或id（实际是主键）向所有订阅该组织信息的学生发送，可以只发给在校学生'''
    try:
        if isinstance(activity_or_id, Activity):
            activity = activity_or_id
        else:
            activity = Activity.objects.get(pk=activity_or_id)
    except:
        print(f"未找到id为{activity_or_id}的活动")
        return False
    org = activity.organization_id
    subcribers = NaturalPerson.objects.difference(
        org.unsubsribers)                   # flat=True时必须只有一个键
    if only_activated:
        subcribers = subcribers.exclude(
            status=NaturalPerson.GraduateStatus.GRADUATED)
    subcribers = list(subcribers.values_list("person_id__username", flat=True))
    num = len(subcribers)
    start, finish = activity.start, activity.finish
    if start.year == datetime.now().year and finish.year == datetime.now().year:
        timeformat = "%m月%d日 %H:%M"       # 一般不显示年和秒
    else:
        timeformat = "%Y年%m月%d日 %H:%M"   # 显示具体年份
    start = start.strftime(timeformat)
    finish = finish.strftime(timeformat)
    content = activity.introduction if not hasattr(
        activity, 'content') else activity.content      # 模型发生了改变
    if len(content) < 120:                  # 卡片类型消息最多显示256字节
        kws = {"card": True}                # 因留白等原因，内容120字左右就超出了
        message = "\n".join((
            activity.title,
            f"组织者：{activity.organization_id.oname}",
            f"活动时间：{start}-{finish}",
            "活动内容：",
            content,
            "点击查看详情"
        ))
        if activity.URL:
            kws["url"] = activity.URL
            kws["btntxt"] = "阅读原文"
    else:                                   # 超出卡片字数范围的消息使用文本格式发送
        kws = {"card": False}
        message = "\n".join((
            activity.title,
            "",
            "组织者：",
            f"{activity.organization_id.oname}",
            "活动时间：",
            f"{start}-{finish}",
            "活动简介：",
            content
        ))
        if activity.URL:
            message += f"\n\n<a href=\"{activity.URL}\">阅读原文</a>"
        else:
            message += f"\n\n<a href=\"{DEFAULT_URL}\">点击查看详情</a>"
    for i in range(0, num, ACTIVITY_BUDGET):
        userids = subcribers[i:i+ACTIVITY_BUDGET]   # 一次最多接受1000个
        if USE_MULTITHREAD:
            # 多线程
            scheduler.add_job(base_send_wechat, 'date',
                              args=(userids, message),
                              kwargs=kws,
                              next_run_time=datetime.now() + timedelta(seconds=5+round(i/50))
                              )
        else:
            base_send_wechat(userids, message, **kws)  # 不使用定时任务请改为这句
    return True
publish_activity.ENABLE_INSTANCE = True     # 标识接收的参数类型
