'''
wechat.py

集合发送到微信的函数

- 可导出函数可以假设是异步IO，参数符合条件时不抛出异常，具体情况见配置文件
- 异步时，函数只返回尝试状态，即是否设置了定时任务，不保证成功发送
- _开头的函数是私有函数，子模块不应调用
'''
import requests
import json
from typing import Iterable, Callable, Any
from datetime import datetime, timedelta

from extern.config import wechat_config as CONFIG
from extern.multithread import get_caller, scheduler_enabled
from extern.log import ExternLogger
from utils.http.utils import build_full_url


__all__ = [
    'send_wechat',
    'send_verify_code',
    'invite_to_wechat',
]


# 全局变量 用来发送和确认默认的导航网址
DEFAULT_URL = build_full_url('/')
logger = ExternLogger.getLogger('wechat')


def _get_available_users(users: Iterable[str | int]) -> list[str]:
    _users = map(str, users)
    _users = set(_users)
    if CONFIG.receivers is not None:
        _users &= CONFIG.receivers
    if CONFIG.blacklist:
        _users -= CONFIG.blacklist
    _users = sorted(_users)
    return _users


ParseResult = tuple[str | None, list[str] | None]
def _post_and_parse(
    post_url: str,
    post_data: dict[str, Any],
    timeout: int | float,
    detail_parser: Callable[[Any], ParseResult] | None = None,
) -> ParseResult:
    '''
    发送post请求并解析回应，返回解析结果，解析结果

    Args:
        post_url(str): 请求的url
        post_data(dict): 请求的数据
        timeout(int | float): 超时时间
        detail_parser(Callable[[Any], ParseResult], optional): 解析回应中细节部分的函数
    
    Returns:
        parseResult: 解析结果，包含错误信息（成功时为None）和建议重发的失败用户列表
    '''
    try: _post_data = json.dumps(post_data)
    except: return "JSON编码失败", None
    try: raw_response = requests.post(post_url, _post_data, timeout=timeout)
    except: return "连接API失败", None
    try: response: dict[str, Any] = raw_response.json()
    except: return "JSON解析失败", None
    try:
        if response["status"] == 200:           # 全部发送成功
            return None, []
        datas: dict = response["data"]
        if datas.get("detail"):                 # 部分发送失败
            assert detail_parser is not None
            return detail_parser(datas["detail"])
        errmsg: str = datas["errMsg"]           # 参数等其他传入格式问题
        return errmsg, None
    except:
        return "回应解析失败", None


def _log_users(users: list[str]) -> str:
    if len(users) <= 10:
        return ', '.join(users)
    user_display = users[:3] + ['...'] + users[-3:]
    return ', '.join(user_display) + f'等{len(users)}用户'


def _send_wechat(
    users: list[str],
    content: str,
    api_url: str,
    card: bool = True,
    url: str | None = None,
    btntxt: str | None = None,
    *,
    retry_times: int = 1,
):
    """底层实现发送到微信，是为了方便设置定时任务"""
    post_data = {
        "touser": users,
        "content": content,
        "toall": True,
        "secret": CONFIG.hasher.encode(content),
    }
    if card:
        post_data["card"] = True
        if url is not None:
            post_data["url"] = url
        if btntxt is not None:
            post_data["btntxt"] = btntxt

    def _parser(detail: list[tuple[str, str]]) -> ParseResult:
        retrys = [x[0] for x in detail]
        errmsg = detail[0][1]             # 失败原因基本相同，取一个即可
        return errmsg, retrys

    for i in range(retry_times):
        errmsg, retrys = _post_and_parse(api_url, post_data, CONFIG.timeout, _parser)
        if errmsg is None:
            logger.info(f"成功向{_log_users(users)}发送消息")
            break
        if retrys is None:
            logger.warning(f"向{_log_users(users)}发送消息失败：{errmsg}")
            break
        post_data["touser"] = retrys
        logger.warning(f"向{_log_users(users)}发送时，{_log_users(retrys)}失败：{errmsg}")


def send_wechat(
    users: Iterable[str | int],
    title: str,
    message: str,
    card: bool = True,
    url: str | None = None,
    btntxt: str | None = None,
    *,
    api_path: str = '',
    default: bool = True,
    retry_times: int = 1,
    multithread: bool = True,
    run_time: datetime | timedelta | None = None,
    task_id: str | None = None,
):
    """
    附带了去重、多线程和batch的发送；不应被服务直接调用

    参数
    --------
    - users(Iterable[str | int]): 用户列表
    - title(str): 标题
    - message(str): 内容，可为空字符串
    - card(bool): 发送文本卡片，建议message长度小于120时开启
    - url(str, optional): 文本卡片的链接，相对路径会被转换为绝对路径
    - btntxt(str, optional): 文本卡片的提示短语，不超过4个字
    - 仅关键字参数
        - api_path(str, optional): API路径，相对路径会被转换为绝对路径
        - default(bool, optional): 填充默认值
        - retry_times(int, optional): 重试次数
        - multithread(bool, optional): 使用多线程（需要启用多线程），不堵塞当前线程
        - run_time(datetime | timedelta, optional): 执行时间，时间或延迟
        - task_id(str, optional): 任务标识符，与定时任务标识符一致
    
    异常
    --------
    - RuntimeError: 定时任务未启用时，设置定时发送时间
    """
    users = _get_available_users(users)
    if not users:
        return logger.warning('没有可用用户')
    content = f'{title}<title>{message}'
    if card:
        if url is not None:
            url = build_full_url(url)
        elif default:
            url = DEFAULT_URL
        if btntxt is None and default:
            btntxt = "详情"
    if not CONFIG.retry:
        retry_times = 1

    if run_time is not None and not scheduler_enabled(multithread):
        if isinstance(run_time, datetime):
            _schedule_time = run_time.strftime('%Y-%m-%d %H:%M:%S')
            _schedule_time = f'计划于{_schedule_time}执行'
        else:
            _schedule_time = f'延迟{run_time}执行'
        logger.error(f'无法设置{_schedule_time}的任务{task_id}：定时任务未启用')
        raise RuntimeError('定时任务未启用')

    total_ct = len(users)
    caller = get_caller(_send_wechat, multithread=multithread,
                        job_id=task_id, run_time=run_time)
    for i in range(0, total_ct, CONFIG.send_batch):
        userids = users[i : i + CONFIG.send_batch]
        caller(
            userids, content, build_full_url(api_path, CONFIG.api_url),
            card=card, url=url, btntxt=btntxt,
            retry_times=retry_times,
        )


def send_verify_code(stu_id: str | int, captcha: str, url: str | None = '/forgetpw/'):
    time = datetime.now().strftime('%m月%d日 %H:%M:%S')
    message = (
        "您的账号正在进行企业微信验证\n本次请求的验证码为："
        f"<div class=\"highlight\">{captcha}</div>"
        f"发送时间：{time}"
    )
    url = build_full_url(url) if url is not None else None
    btntxt = "登录" if url is not None else None
    send_wechat([stu_id], 'YPPF登录验证', message,
                card=True, url=url, btntxt=btntxt,
                task_id=f'wechat_verify: {stu_id}')


def _invite_to_wechat(stu_id: str, retry_times: int = 1):
    INVITE_URL = build_full_url('/invite_user', CONFIG.api_url)
    post_data = {
        "user": stu_id,
        "secret": CONFIG.hasher.encode(stu_id),
    }

    def _parser(detail: str) -> ParseResult:
        return detail, [stu_id]

    for i in range(retry_times):
        errmsg, retrys = _post_and_parse(INVITE_URL, post_data, CONFIG.timeout, _parser)
        if errmsg is None:
            logger.info(f"成功向{stu_id}发送邀请")
            break
        logger.warning(f"向{stu_id}发送邀请失败：{errmsg}")
        if retrys is None: break


def invite_to_wechat(stu_id: str | int, retry_times: int = 3, *, multithread: bool = True):
    caller = get_caller(_invite_to_wechat, multithread=multithread)
    caller(str(stu_id), retry_times=retry_times)
