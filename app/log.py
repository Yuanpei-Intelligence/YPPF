import threading
import os
from boottest import local_dict
from datetime import datetime, timedelta

from functools import wraps
import traceback
import json
import hashlib

from django.conf import settings

__all__ = [
    'STATE_DEBUG', 'STATE_INFO', 'STATE_WARNING', 'STATE_ERROR',
    'operation_writer',
    'except_captured',
    'record_traceback',
]

# 状态常量
STATE_DEBUG = 'Debug'
STATE_INFO = 'Info'
STATE_WARNING = 'Warning'
STATE_ERROR = 'Error'


# 线程锁，用于对文件写入的排他性
__lock = threading.RLock()
# 记录最低等级
__log_level = STATE_INFO
# 文件操作体系
__log_root = "logstore"
if not os.path.exists(__log_root):
    os.mkdir(__log_root)
__log_root_path = os.path.join(os.getcwd(), __log_root)
if os.getenv("YPPF_ENV") in ["PRODUCT", "TEST"]:
    __log_root_path = os.environ["YPPF_LOG_DIR"]
__log_user = "user_detail"
if not os.path.exists(os.path.join(__log_root_path, __log_user)):
    os.mkdir(os.path.join(__log_root_path, __log_user))
__log_user_path = os.path.join(__log_root_path, __log_user)
__log_detailed_path = os.path.join(__log_root_path, "traceback_record")

def status_enabled(status_code: str):
    # 待完善，半成品
    level_up = [STATE_DEBUG, STATE_INFO, STATE_WARNING, STATE_ERROR]
    try:
        return level_up.index(status_code) >= level_up.index(__log_level)
    except:
        return False


# 通用日志写入程序 写入时间(datetime.now()),操作主体(Sid),操作说明(Str),写入函数(Str)
# 参数说明：第一为Sid也是文件名，第二位消息，第三位来源的函数名（类别）
# 如果是系统相关的 请写local_dict["system_log"]
def operation_writer(user, message, source=None, status_code: str=STATE_INFO):
    if not status_enabled(status_code):
        return
    
    __lock.acquire()
    try:
        timestamp = str(datetime.now())
        source = str(source).ljust(30)
        status = status_code.ljust(10)
        message = f"{timestamp} {source}{status}: {message}\n"

        with open(os.path.join(__log_user_path, f"{str(user)}.log"), mode="a") as journal:
            journal.write(message)

        if status_code == STATE_ERROR and local_dict.get('debug_stuids'):
            from app.wechat_send import send_wechat
            receivers = list(local_dict['debug_stuids'])
            if isinstance(receivers, str):
                receivers = receivers.replace(' ', '').split(',')
            receivers = list(map(str, receivers))
            send_message = message
            if len(send_message) > 400:
                send_message = '\n'.join([
                    send_message[:300],
                    '...',
                    send_message[-100:],
                    '详情请查看log'
                ])
            send_wechat(receivers, f'YPPF {settings.MY_ENV}发生异常\n' + send_message, card=len(message) < 200)
    except Exception as e:
        # 最好是发送邮件通知存在问题
        # TODO:
        print(e)
    finally:
        __lock.release()


def except_captured(return_value=None, except_type=Exception,
                    log=True, show_traceback=False, record_args=False,
                    record_user=False, record_request_args=False,
                    source='utils[except_captured]', status_code=STATE_ERROR):
    """
    Decorator that captures exception and log, raise or 
    return specific value if `return_value` is assigned.
    """

    def actual_decorator(view_function):
        @wraps(view_function)
        def _wrapped_view(*args, **kwargs):
            try:
                return view_function(*args, **kwargs)
            except except_type as e:
                if log:
                    msg = f'发生意外的错误：{e}'
                    if record_args:
                        msg += f', 参数为：{args=}, {kwargs=}'
                    if record_user:
                        try:
                            user = None
                            if not args:
                                if 'request' in kwargs.keys():
                                    user = kwargs["request"].user
                                elif 'user' in kwargs.keys():
                                    user = kwargs["user"]
                            else:
                                user = args[0].user
                            msg += f', 用户为{user.username}'
                            try: msg += f', 姓名: {user.naturalperson}'
                            except: pass
                            try: msg += f', 组织名: {user.organization}'
                            except: pass
                        except:
                            msg += f', 尝试追踪用户, 但未能找到该参数'
                    if record_request_args:
                        try:
                            request = None
                            if not args:
                                request = kwargs["request"]
                            else:
                                request = args[0]
                            infos = []
                            infos.append(f'请求方式: {request.method}, 请求地址: {request.path}')
                            if request.GET:
                                infos.append(
                                    'GET参数: ' +
                                    ';'.join([f'{k}: {v}' for k, v in request.GET.items()])
                                )
                            if request.POST:
                                infos.append(
                                    'POST参数: ' +
                                    ';'.join([f'{k}: {v}' for k, v in request.POST.items()])
                                )
                            msg = msg + '\n' + '\n'.join(infos)
                        except:
                            msg += f'\n尝试记录请求体, 但未能找到该参数'
                    if show_traceback:
                        msg += '\n详细信息：\n\t'
                        msg += traceback.format_exc().replace('\n', '\n\t')
                    operation_writer(local_dict['system_log'],
                        msg, source, status_code)
                if return_value is not None:
                    return return_value
                raise

        return _wrapped_view

    return actual_decorator


def record_traceback(request, e):
    '''尽量避免使用本函数'''
    d = {}
    d["time"] = datetime.now().strftime("%Y/%m/%d-%H%M")
    d["username"] = request.user.username
    d["request_path"] = request.path
    if request.GET:
        d["GET_Param"] = request.GET
    if request.POST:
        d["POST_Param"] = request.POST
    d["traceback"] = traceback.format_exc()

    hash_value = hashlib.sha1(json.dumps(d).encode()).digest().hex()
    __log_dir = os.path.join(__log_detailed_path, request.user.username)
    __log_path = os.path.join(__log_dir, hash_value + ".json")
    os.makedirs(__log_dir, exist_ok=True)
    with open(__log_path, "w") as f:
        json.dump(d, f)

    if local_dict.get('debug_stuids'):
        from app.wechat_send import send_wechat
        receivers = list(local_dict['debug_stuids'])
        if isinstance(receivers, str):
            receivers = receivers.replace(' ', '').split(',')
        receivers = list(map(str, receivers))
        message = f"错误类型：{type(e)}\n + 记录路径：{__log_path}\n"
        send_wechat(receivers, f'YPPF {settings.MY_ENV} 记录到错误详情\n' + f"记录路径：{__log_path}")
