'''
wechat.py

集合了需要发送到微信的函数

调用提示
    base开头的函数是基础函数，通常作为定时任务，无返回值，但可能打印报错信息
    其他函数可以假设是异步IO，参数符合条件时不抛出异常
    由于异步假设，函数只返回尝试状态，即是否设置了定时任务，不保证成功发送
'''
import requests
import json
from datetime import datetime, timedelta

from extern.config import wechat_config as CONFIG
from utils.hasher import MySHA256Hasher
from utils.http.utils import build_full_url
from scheduler.scheduler import scheduler


__all__ = [
    'send_wechat',
    'send_wechat_captcha',
    'invite',
]


# 全局设置
# 是否启用定时任务，请最好仅在服务器启用，如果不启用，后面的多个设置也会随之变化
USE_SCHEDULER = CONFIG.use_scheduler
# 是否多线程发送，必须启用scheduler，如果启用则发送时无需等待
USE_MULTITHREAD = True if USE_SCHEDULER else False
# 决定单次连接的超时时间，响应时间一般为1s或12s（偶尔），建议考虑前端等待时间放弃12s
TIMEOUT = 15 if USE_MULTITHREAD else 5 or 3.05 or 12 or 15
# 订阅系统的发送量非常大，不建议重发，因为发送失败之后短时间内重发大概率也会失败
# 如果未来实现重发，应在base_send_wechat中定义作为参数读入，现在提供了几句简单的代码
RETRY = CONFIG.retry

# 全局变量 用来发送和确认默认的导航网址
DEFAULT_URL = build_full_url('/')
THIS_URL = DEFAULT_URL.rstrip('/')        # 增加默认url前缀, 去除尾部的/
WECHAT_SITE = CONFIG.api_url.rstrip('/')    # 去除尾部的/
INVITE_URL = WECHAT_SITE + '/invite_user'
wechat_coder = MySHA256Hasher(CONFIG.salt)

# 发送应用设置
# 应用名到域名的转换，可以是相对地址，也可以是绝对地址
APP2URL = CONFIG.app2url
APP2URL.setdefault('default', '')


# 一批发送的最大数量
# 底层单次发送的上限，不超过1000
SEND_LIMIT = CONFIG.send_limit
# 中间层一批发送的数量，不超过1000
SEND_BATCH = CONFIG.send_batch

# 限制接收范围
# 可接收范围，默认全体(None表示不限制范围)
RECEIVER_SET = CONFIG.receivers
# 黑名单，默认没有，可以用来排除元培学院等特殊用户
BLACKLIST_SET = CONFIG.blacklist


def app2absolute_url(app):
    '''default必须被定义 这里放宽了'''
    url = APP2URL.get(app)
    if url is None:
        url = APP2URL.get('default', '')
    if not url.startswith('http'):
        if not url:
            url = WECHAT_SITE
        else:
            url = WECHAT_SITE + '/' + url.lstrip('/')
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
    - message: 一段文字，第一个`\\n`被视为标题和内容的分隔符
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
