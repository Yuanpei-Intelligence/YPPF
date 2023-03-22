import logging
from datetime import datetime, timedelta

from django.db.models import QuerySet

from Appointment.models import (
    User,
    Participant,
    Room,
    Appoint,
    LongTermAppoint,
    CardCheckInfo,
)
from Appointment.apps import AppointmentConfig as AppConfig
from boot.config import GLOBAL_CONFIG
from record.log.logger import Logger
from utils.inspect import find_caller


__all__ = [
    "cardcheckinfo_writer",
    "write_before_delete",
    "logger",
    "get_user_logger",
]


def cardcheckinfo_writer(user: Participant | None, room: Room, real_status, message=None):
    CardCheckInfo.objects.create(
        Cardroom=room, Cardstudent=user,
        CardStatus=real_status, Message=message
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


class AppointmentLogger(Logger):
    def _log(self, level, msg, args, exc_info = None, extra = None, stack_info = False, stacklevel = 1) -> None:
        stacklevel = stacklevel + 1
        file, caller, lineno = find_caller(stacklevel)
        file = file.removeprefix('Appointment.')
        source = f'{file}.{caller}'
        msg = str(msg)
        log_msg = source.ljust(40) + msg
        super()._log(level, log_msg, args, exc_info, extra, stack_info, stacklevel)
        if level >= logging.ERROR:
            self._send_wechat(f'错误位置：{source} {lineno}行\n' + msg, level)

    def _send_wechat(self, message: str, level: int = logging.ERROR):
        if not GLOBAL_CONFIG.debug_stuids:
            return
        from extern.wechat import send_wechat
        send_wechat(
            GLOBAL_CONFIG.debug_stuids,
            '地下室发生错误', message,
        )


class UserLogger(AppointmentLogger):
    def add_default_handler(self, name: str, *paths: str) -> None:
        return super().add_default_handler(name, 'user_detail', *paths)


logger = AppointmentLogger.getLogger(AppConfig.name)

def get_user_logger(source: User | Participant | Appoint | LongTermAppoint | str):
    '''获取用户日志记录器'''
    match source:
        case User():
            name = source.get_username()
        case Participant():
            name = source.get_id()
        case Appoint():
            name = source.get_major_id()
        case LongTermAppoint():
            name = source.get_applicant_id()
        case str():
            name = source
        case _:
            name = 'unknown'
    return UserLogger.getLogger(name)
