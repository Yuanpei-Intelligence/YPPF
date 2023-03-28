from datetime import datetime, timedelta

from Appointment.models import Appoint
from Appointment.extern.constants import MessageType
from Appointment.extern.wechat import notify_appoint
from scheduler.cancel import remove_job


__all__ = [
    'set_appoint_reminder',
    'remove_appoint_reminder',
]


def _remind_job_id(appoint_id: int) -> str:
    return f'{appoint_id}_appoint_remind'


def set_appoint_reminder(appoint: Appoint, students_id: list[str] | None = None, *,
                         scheduled_only: bool = True) -> bool:
    '''设置预约开始前的提醒，根据时间决定如何发送，任何时刻均可调用，开始后不提醒'''
    if datetime.now() >= appoint.Astart:
        return False
    if datetime.now() > appoint.Astart - timedelta(minutes=15):
        if scheduled_only:
            return False
        job_time = None
    else:
        job_time = appoint.Astart - timedelta(minutes=15)
    notify_appoint(appoint, MessageType.REMIND, students_id=students_id,
                   id=_remind_job_id(appoint.Aid), job_time=job_time)
    return True


def remove_appoint_reminder(appoint_id: int, no_except: bool = True):
    '''取消预约开始前的提醒，不进行任何日志记录，返回值同`remove_job`'''
    return remove_job(_remind_job_id(appoint_id), no_except=no_except)
