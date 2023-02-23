import logging
from datetime import datetime, timedelta

from django.db.models import QuerySet

from Appointment.models import (
    User,
    Participant,
    Room,
    Appoint,
    CardCheckInfo,
)
from Appointment.apps import AppointmentConfig as AppConfig
from utils.log.logger import Logger
from boot.config import GLOBAL_CONF
from utils.inspect import find_caller


__all__ = [
    "cardcheckinfo_writer",
    "write_before_delete",
    "operation_writer",
    "logger",
]


def cardcheckinfo_writer(user: Participant, room: Room, real_status, should_status, message=None):
    CardCheckInfo.objects.create(
        Cardroom=room, Cardstudent=user,
        CardStatus=real_status, ShouldOpenStatus=should_status, Message=message
    )


class AppointRecordLogger(Logger):
    def add_default_handler(self, name: str, *paths: str) -> None:
        return super().add_default_handler(
            name, 'appoint_record', *paths, format='%(message)s')


def write_before_delete(appoint_list: QuerySet[Appoint]):
    """每周定时删除预约的程序，用于减少系统内的预约数量"""
    date = str(datetime.now().date())
    logger = AppointRecordLogger.getLogger(date)
    period_start = (datetime.now() - timedelta(days=7)).date()
    logger.info(f"{period_start}~{date}")
    for appoint in appoint_list.exclude(Astatus=Appoint.Status.CANCELED):
        logger.info(appoint.toJson())
    logger.info("end of file")


def operation_writer(message: str,
                     status_code: str = "OK",
                     user: str | User | Participant | None = None) -> None:
    """
    通用日志写入程序 错误时发送微信提示

    :param message: 消息
    :type message: str
    :param status_code: 状态, defaults to "OK", 可用值为OK Problem Error
    :type status_code: str, optional
    :param user: Sid，决定文件名, `None`使用新日志方法
    :type user: str | User | Participant | None
    """
    # 发送微信
    try:
        if user is None:
            _logger = logger
        else:
            _logger = AppointmentLogger.getLogger(str(user))
        match status_code:
            case "OK":
                _logger.info(message)
            case "Problem":
                _logger.warning(message)
            case "Error":
                _logger.error(message)
    except Exception as e:
        logger.exception('opration_writer failed')


class AppointmentLogger(Logger):
    def setup(self, name: str, handle: bool = True, root: bool = False) -> None:
        super().setup(name, handle=False, root=root)
        if not handle:
            return
        if root:
            self.add_default_handler(name)
        else:
            self.add_default_handler(name, 'user_detail')


    def _log(self, level, msg, args, exc_info = None, extra = None, stack_info = False, stacklevel = 1) -> None:
        file, caller, _ = find_caller(depth=3)
        source = f"{file}.{caller}"
        msg = source.ljust(40) + str(msg)
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)
        if level >= logging.ERROR:
            self._send_wechat(msg, level)

    def _send_wechat(self, message: str, level: int = logging.ERROR):
        if not GLOBAL_CONF.debug_stuids:
            return
        from Appointment.extern.wechat import send_wechat_message
        from Appointment.extern.constants import MessageType
        send_wechat_message(
            stuid_list=GLOBAL_CONF.debug_stuids,
            start_time=datetime.now(),
            room='地下室后台',
            message_type=MessageType.ADMIN.value,
            major_student="地下室系统",
            usage="发生Error错误",
            announcement="",
            num=1,
            reason=message,
        )

logger = AppointmentLogger.getLogger(AppConfig.name, root=True)
