from datetime import datetime, timedelta

from Appointment.models import Appoint
from Appointment.extern.constants import MessageType
from Appointment.extern.wechat import notify_appoint
from Appointment.utils.log import logger


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
