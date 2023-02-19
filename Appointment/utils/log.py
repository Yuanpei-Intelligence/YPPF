import os
import threading
from datetime import datetime, timedelta

from django.db.models import QuerySet

from Appointment.models import (
    User,
    Participant,
    Room,
    Appoint,
    CardCheckInfo,
)
from Appointment.config import CONFIG, logger
from boot.config import BASE_DIR


__all__ = [
    "cardcheckinfo_writer",
    "write_before_delete",
    "operation_writer",
]


log_root = "logstore"
if not os.path.exists(log_root):
    os.mkdir(log_root)
log_root_path = os.path.join(BASE_DIR, log_root)
log_user = "user_detail"
if not os.path.exists(os.path.join(log_root_path, log_user)):
    os.mkdir(os.path.join(log_root_path, log_user))
log_user_path = os.path.join(log_root_path, log_user)
lock = threading.RLock()


def cardcheckinfo_writer(user: Participant, room: Room, real_status, should_status, message=None):
    CardCheckInfo.objects.create(
        Cardroom=room, Cardstudent=user,
        CardStatus=real_status, ShouldOpenStatus=should_status, Message=message
    )


def write_before_delete(appoint_list: QuerySet[Appoint]):
    """每周定时删除预约的程序，用于减少系统内的预约数量"""
    date = str(datetime.now().date())

    write_path = os.path.join(log_root_path, date + ".log")
    with open(write_path, mode="a") as log:
        period_start = (datetime.now() - timedelta(days=7)).date()
        log.write(f"{period_start}~{date}\n")
        for appoint in appoint_list:
            if appoint.Astatus != Appoint.Status.CANCELED:
                log.write(str(appoint.toJson()) + "\n")
        log.write("end of file\n")


def _original_writer(user: str | User | Participant, message: str, source: str,
                     status_code="OK") -> None:
    """
    通用日志写入程序 写入时间(datetime.now()),操作主体(Sid),操作说明(Str),写入函数(Str)

    :param user: Sid，决定文件名
    :type user: Union[str, User, Participant]
    :param message: 消息
    :type message: str
    :param source: 来源的函数名，格式通常为 文件名.函数名
    :type source: str
    :param status_code: 状态, defaults to "OK"
    :type status_code: str, optional
    """
    if isinstance(user, Participant):
        user = user.Sid_id
    if isinstance(user, User):
        user = user.username
    timestamp = str(datetime.now())
    source = str(source).ljust(30)
    status = status_code.ljust(10)
    message = f"{timestamp} {source}{status}: {message}\n"

    with open(os.path.join(log_user_path, f"{str(user)}.log"), mode="a") as journal:
        journal.write(message)


def operation_writer(user: str | User | Participant | None, message: str, source: str,
                     status_code="OK") -> None:
    """
    通用日志写入程序 错误时发送微信提示

    :param user: Sid，决定文件名, `None`使用新日志方法
    :type user: str | User | Participant | None
    :param message: 消息
    :type message: str
    :param source: 来源的函数名，格式通常为 文件名.函数名
    :type source: str
    :param status_code: 状态, defaults to "OK", 可用值为OK Problem Error
    :type status_code: str, optional
    """
    lock.acquire()
    if user is None:
        func_map = dict(
            # 原先的状态名
            OK="info", Problem="warning", Error="error",
            # logger支持的函数名
            debug="debug", info="info", warning="warning", warn="warn",
            error="error", exception="exception",
        )
        assert status_code in func_map.keys(), "非法的状态名"
        func_name = func_map[status_code]
        log_func = getattr(logger, func_name, logger.exception)
        log_func(message, source)
    else:
        _original_writer(user, message, source, status_code)
    # 发送微信
    try:
        if isinstance(user, Participant):
            user = user.Sid_id
        if isinstance(user, User):
            user = user.username
        timestamp = str(datetime.now())
        source = str(source).ljust(30)
        status = status_code.ljust(10)
        message = f"{timestamp} {source}{status}: {message}\n"

        with open(os.path.join(log_user_path, f"{str(user)}.log"), mode="a") as journal:
            journal.write(message)

        if status_code == "Error" and CONFIG.debug_stuids:
            from Appointment.extern.wechat import send_wechat_message
            send_wechat_message(
                stuid_list=CONFIG.debug_stuids,
                start_time=datetime.now(),
                room='地下室后台',
                message_type="admin",
                major_student="地下室系统",
                usage="发生Error错误",
                announcement="",
                num=1,
                reason=message,
            )
    except Exception as e:
        logger.exception('opration_writer failed')

    lock.release()

