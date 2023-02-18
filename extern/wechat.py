'''
wechat.py

集合发送到微信的函数

- 可导出函数可以假设是异步IO，参数符合条件时不抛出异常，具体情况见配置文件
- 异步时，函数只返回尝试状态，即是否设置了定时任务，不保证成功发送
- _开头的函数是私有函数，子模块不应调用
'''
import requests
import json
from typing import Callable, ParamSpec, TypeVar, Any
from datetime import datetime, timedelta

from extern.config import wechat_config as CONFIG
from utils.http.utils import build_full_url
from scheduler.scheduler import scheduler


__all__ = [
    'send_wechat',
    'send_verify_code',
    'invite_to_wechat',
]


# 全局变量 用来发送和确认默认的导航网址
DEFAULT_URL = build_full_url('/')


def app2absolute_url(app: str) -> str:
    '''default必须被定义 这里放宽了'''
    url = CONFIG.app2url.get(app)
    if url is None:
        url = CONFIG.app2url.get('default', '')
    return build_full_url(url, CONFIG.api_url)


_P = ParamSpec('_P')
_T = TypeVar('_T')
def _get_caller(func: Callable[_P, _T], multithread: bool = True,
                next_run_time: datetime | timedelta | None = None):
    '''获取函数的调用者'''
    multithread = multithread and CONFIG.multithread
    if not multithread:
        return func
    def _func(*args: _P.args, **kwargs: _P.kwargs):
        if isinstance(next_run_time, datetime):
            _next_run = next_run_time
        elif isinstance(next_run_time, timedelta):
            _next_run = datetime.now() + next_run_time
        else:
            _next_run = datetime.now() + timedelta(seconds=5)
        scheduler.add_job(
            func,
            "date",
            args=args,
            kwargs=kwargs,
            next_run_time=_next_run,
        )
    return _func


def _send_wechat(users, message, app='default',
                     card=True, url=None, btntxt=None, default=True):
    """底层实现发送到微信，是为了方便设置定时任务"""
    post_url = app2absolute_url(app)

    if CONFIG.receivers is not None:
        users = sorted((set(users) & CONFIG.receivers) - CONFIG.blacklist)
    elif CONFIG.blacklist is not None and CONFIG.blacklist:
        users = sorted(set(users) - CONFIG.blacklist)
    else:
        users = sorted(users)
    user_num = len(users)
    if user_num == 0:
        print("没有合法的用户")
        return
    if user_num > CONFIG.send_limit:
        removed_rep = users[CONFIG.send_limit: CONFIG.send_limit+3]
        print("用户列表过长,", f"{removed_rep}等{user_num-CONFIG.send_limit}人被舍去")
        users = users[:CONFIG.send_limit]
    post_data = {
        "touser": users,
        "content": message,
        "toall": True,
        "secret": CONFIG.hasher.encode(message),
    }
    if card:
        if url is not None and url[:1] in ["", "/"]:  # 空或者相对路径，变为绝对路径
            url = build_full_url(url)
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
    # if not CONFIG.retry or not retry_times:
    #     retry_times = 1
    # for i in range(retry_times):
    try:
        failed = users
        errmsg = "连接api失败"
        response = requests.post(post_url, post_data, timeout=CONFIG.timeout)
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

    参数
    --------
    - users: 随机访问容器，如果检查重复，则可以是任何可迭代对象
    - message: 一段文字，第一个`\\n`被视为标题和内容的分隔符
    - app: 标识应用名的字符串，可以直接使用WechatApp的宏
    - card: 发送文本卡片，建议message长度小于120时开启
    - url: 文本卡片的链接，相对路径会被转换为绝对路径
    - btntxt: 文本卡片的提示短语，不超过4个字
    - default: 填充默认值
    - 仅关键字参数
    - multithread: 不堵塞线程
    - check_duplicate: 检查重复值
    """
    if check_duplicate:
        users = sorted(set(users))
    total_ct = len(users)
    SEND_BATCH = min(CONFIG.send_batch, CONFIG.send_limit)
    caller = _get_caller(_send_wechat, multithread=multithread)
    for i in range(0, total_ct, SEND_BATCH):
        userids = users[i : i + SEND_BATCH]  # 一次最多接受1000个
        caller(
            userids, message, app,
            card=card, url=url, btntxt=btntxt, default=default,
        )


def send_verify_code(stu_id: str | int, captcha: str, url: str = '/forgetpw/'):
    users = [stu_id]
    kws = {}
    kws["card"] = True
    message = (
        "YPPF登录验证\n"
        "您的账号正在进行企业微信验证\n本次请求的验证码为："
        f"<div class=\"highlight\">{captcha}</div>"
        f"发送时间：{datetime.now().strftime('%m月%d日 %H:%M:%S')}"
    )
    if url:
        kws["url"] = build_full_url(url)
        kws["btntxt"] = "登录"
    send_wechat(users, message, **kws)


def _invite_to_wechat(stu_id: str, retry_times: int = 1):
    post_data = {
        "user": stu_id,
        "secret": CONFIG.hasher.encode(stu_id),
    }
    post_data = json.dumps(post_data)
    for i in range(retry_times):
        end = False
        errmsg = "连接api失败"
        try:
            INVITE_URL = build_full_url('/invite_user', CONFIG.api_url)
            response = requests.post(INVITE_URL, post_data, timeout=CONFIG.timeout)
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


def invite_to_wechat(stu_id: str | int, retry_times: int = 3, *, multithread: bool = True):
    caller = _get_caller(_invite_to_wechat, multithread=multithread)
    caller(str(stu_id), retry_times=retry_times)
