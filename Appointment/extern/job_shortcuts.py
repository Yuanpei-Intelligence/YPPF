from datetime import datetime, timedelta

from Appointment.models import Appoint, LongTermAppoint
from Appointment.extern.constants import MessageType
from Appointment.extern.wechat import notify_appoint
from Appointment.utils.log import logger
from scheduler.scheduler import scheduler


__all__ = [
    'notify_create',
    'set_appoint_reminder',
    'remove_appoint_reminder',
    'notify_longterm_review',
]


def notify_create(appoint: Appoint, students_id: list[str] | None = None) -> bool:
    '''提醒有新预约，根据时间和预约类型决定如何发送'''
    if appoint.Atype == Appoint.Type.TEMPORARY:
        notify_appoint(appoint, MessageType.TEMPORARY, students_id=students_id)
        return True
    if datetime.now() >= appoint.Astart:
        logger.warning(f'预约{appoint.Aid}尝试发送给微信时已经开始，且并非临时预约')
        return False
    if datetime.now() <= appoint.Astart - timedelta(minutes=15):
        notify_appoint(appoint, MessageType.NEW, students_id=students_id)
    else:
        notify_appoint(appoint, MessageType.NEW_INCOMING, students_id=students_id)
    return True


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


def remove_appoint_reminder(appoint_id: int):
    '''取消预约开始前的提醒，不进行任何错误处理或日志记录'''
    return scheduler.remove_job(_remind_job_id(appoint_id))


def notify_longterm_review(longterm: LongTermAppoint, auditor_ids: list[str]):
    '''长期预约的审核老师通知提醒，发送给对应的审核老师'''
    if not auditor_ids:
        return
    infos = []
    if longterm.get_applicant_id() != longterm.appoint.get_major_id():
        infos.append(f'申请者：{longterm.applicant.name}')
    notify_appoint(longterm, MessageType.LONGTERM_REVIEWING, *infos,
                   students_id=auditor_ids, url=f'review?Lid={longterm.pk}')
