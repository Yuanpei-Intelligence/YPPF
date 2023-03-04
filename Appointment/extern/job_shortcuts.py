from datetime import datetime, timedelta

from Appointment.models import Appoint, LongTermAppoint
from Appointment.extern.constants import MessageType
from Appointment.extern.wechat import notify_appoint
from Appointment.utils.log import logger


__all__ = [
    'remind_job_id',
    'set_start_wechat',
    'notify_longterm_review',
]


def remind_job_id(appoint_id: int) -> str:
    return f'{appoint_id}_start_wechat'


def set_start_wechat(appoint: Appoint, students_id=None, notify_create=True):
    '''将预约成功和开始前的提醒定时发送给微信'''
    if students_id is None:
        students_id = list(appoint.students.values_list('Sid', flat=True))
    if datetime.now() >= appoint.Astart:
        if appoint.Atype == Appoint.Type.TEMPORARY:
            notify_appoint(appoint, MessageType.TEMPORARY,
                students_id=students_id, id=f'{appoint.Aid}_new_wechat')
        else:
            logger.warning(f'预约{appoint.Aid}尝试发送给微信时已经开始，且并非临时预约')
            return False
    elif datetime.now() <= appoint.Astart - timedelta(minutes=15):
        # 距离预约开始还有15分钟以上，提醒有新预约&定时任务
        if notify_create:  # 只有在非长线预约中才添加这个job
            notify_appoint(
                appoint, MessageType.NEW,
                students_id=students_id, id=f'{appoint.Aid}_new_wechat')
        notify_appoint(
            appoint, MessageType.START,
            students_id=students_id, id=remind_job_id(appoint.Aid),
            job_time=appoint.Astart - timedelta(minutes=15))
    else:
        # 距离预约开始还有不到15分钟，提醒有新预约并且马上开始
        notify_appoint(
            appoint, MessageType.NEW_AND_START,
            students_id=students_id, id=f'{appoint.Aid}_new_wechat')
    return True


def notify_longterm_review(longterm_appoint: LongTermAppoint, auditor_ids: list[str]):
    '''长期预约的审核老师通知提醒，发送给对应的审核老师'''
    if not auditor_ids:
        return
    infos = []
    if longterm_appoint.applicant != longterm_appoint.appoint.major_student:
        infos.append(f'申请者：{longterm_appoint.applicant.name}')
    notify_appoint(
        longterm_appoint.appoint, MessageType.LONGTERM_REVIEWING, *infos,
        students_id=auditor_ids,
        url=f'review?Lid={longterm_appoint.pk}',
        id=f'{longterm_appoint.pk}_longterm_review_wechat')
