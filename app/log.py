import os
import logging
from datetime import datetime
from functools import wraps

from django.conf import settings

from utils.log.logger import Logger
from utils.inspect import find_caller
from boot.config import BASE_DIR, GLOBAL_CONF
from extern.wechat import send_wechat
from app.apps import AppConfig


__all__ = [
    'STATE_DEBUG', 'STATE_INFO', 'STATE_WARNING', 'STATE_ERROR',
    'operation_writer',
    'except_captured',
]

# 状态常量
STATE_DEBUG = 'Debug'
STATE_INFO = 'Info'
STATE_WARNING = 'Warning'
STATE_ERROR = 'Error'


# 记录最低等级
__log_level = STATE_INFO
# 文件操作体系
__log_root = "logstore"
if not os.path.exists(__log_root):
    os.mkdir(__log_root)
__log_root_path = os.path.join(BASE_DIR, __log_root)
if os.getenv("YPPF_ENV") in ["PRODUCT", "TEST"]:
    __log_root_path = os.environ["YPPF_LOG_DIR"]
__log_user = "user_detail"
if not os.path.exists(os.path.join(__log_root_path, __log_user)):
    os.mkdir(os.path.join(__log_root_path, __log_user))
__log_user_path = os.path.join(__log_root_path, __log_user)


# 记录相关的常量
SYSTEM_LOG = 'deprecated'


class AppLogger(Logger):
    def setup(self, name: str, handle: bool = True) -> None:
        super().setup(name, handle=False, root=root)
        if not handle:
            return
        if root:
            self.add_default_handler(name)
        else:
            self.add_default_handler(name, 'user_detail')

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1) -> None:
        file, caller, _ = find_caller(depth=3)
        source = f"{file}.{caller}"
        msg = source.ljust(30) + str(msg)
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)
        if level >= logging.ERROR:
            self._send_wechat(msg, level)

    def _send_wechat(self, message: str, level: int = logging.ERROR):
        send_wechat(
            users=GLOBAL_CONF.debug_stuids,
            message=f'Message from Profile Logger\n' + message,
        )

logger = AppLogger.getLogger(AppConfig.name, root=True)

def status_enabled(status_code: str):
    # 待完善，半成品
    level_up = [STATE_DEBUG, STATE_INFO, STATE_WARNING, STATE_ERROR]
    try:
        return level_up.index(status_code) >= level_up.index(__log_level)
    except:
        return False


def operation_writer(user: str, message: str, source: str = '', status_code: str = STATE_INFO):
    '''
    通用日志写入程序
    - 写入时间, 操作主体(user), 操作说明(Str),写入函数(Str)
    - 参数说明：第一为Sid也是文件名，第二位消息，第三位来源的函数名（类别）
    - 如果是系统相关的 请写SYSTEM_LOG
    '''
    if not status_enabled(status_code):
        return

    try:
        timestamp = datetime.now()
        status = status_code.ljust(10)
        file_message = f"{timestamp} {str(source).ljust(30)} {status}: {message}\n"

        with open(os.path.join(__log_user_path, f"{str(user)}.log"), mode="a") as journal:
            journal.write(file_message)

        if status_code == STATE_ERROR and DEBUG_IDS:
            send_message = f'{source} {timestamp}: {message}'
            if len(send_message) > 400:
                send_message = '\n'.join([
                    send_message[:300],
                    '...',
                    send_message[-100:],
                    '详情请查看log'
                ])
            send_wechat(
                DEBUG_IDS, f'YPPF {settings.MY_ENV}发生异常\n' + send_message, card=len(message) < 200)
    except Exception as e:
        # 最好是发送邮件通知存在问题
        # TODO:
        print(e)


def except_captured(return_value=None, except_type=Exception,
                    log=True, show_traceback=False, record_args=False,
                    record_user=False, record_request_args=False,
                    source='utils[except_captured]', status_code=STATE_ERROR):
    """
    Decorator that captures exception and log, raise or 
    return specific value if `return_value` is assigned.
    """

    return logger.secure_view(fail_value=return_value, exc_type=except_type)
