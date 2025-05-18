from datetime import datetime, timedelta

from Appointment.models import Appoint
from Appointment.utils.log import logger
from Appointment.appoint.status_control import (
    start_appoint_ahead, start_appoint, finish_appoint
)
from Appointment.extern.jobs import remove_appoint_reminder
from scheduler.adder import ScheduleAdder
from scheduler.cancel import remove_job
from scheduler.periodic import periodical


@logger.secure_func('设置预约定时任务出错', fail_value=False)
def set_scheduler(appoint: Appoint) -> bool:
    '''
    设置预约状态变更的定时任务，可在任何时候调用，不抛出异常

    Args:
        appoint (Appoint): 预约对象，尚未结束且开始结束顺序正常

    Returns:
        bool: 是否设置成功，当不符合条件时返回False
    '''
    start_ahead = appoint.Astart - timedelta(minutes=10)
    start = appoint.Astart
    finish = appoint.Afinish
    current_time = datetime.now() + timedelta(seconds=5)
    if finish < start:          # 开始晚于结束，预约不合规
        logger.error(f'预约{appoint.pk}时间为{start}<->{finish}，未能设置定时任务')
        return False            # 直接返回，预约不需要设置
    if finish < current_time:   # 预约已经结束
        logger.error(f'预约{appoint.pk}在设置定时任务时已经结束')
        return False            # 直接返回，预约不需要设置
    has_started = start < current_time
    if has_started:             # 临时预约或特殊情况下设置任务时预约可能已经开始
        start = current_time    # 改为立刻执行

    if current_time < start_ahead:
        ScheduleAdder(start_appoint_ahead, id=f'{appoint.pk}_start_ahead',
                      run_time=start_ahead)(appoint.pk)
    elif current_time < start:
        start_appoint_ahead(appoint.pk)

    if not (has_started and appoint.Astatus == Appoint.Status.PROCESSING):
        ScheduleAdder(start_appoint, id=f'{appoint.pk}_start',
                      run_time=start)(appoint.pk)

    ScheduleAdder(finish_appoint, id=f'{appoint.pk}_finish',
                  run_time=finish)(appoint.pk)
    return True


def cancel_scheduler(appoint: Appoint | int, record_miss: bool = False) -> bool:
    '''
    取消预约的定时任务，不抛出异常

    Hint:
        如果结束任务不存在，则不会处理其它任务
    '''
    aid = appoint.pk if isinstance(appoint, Appoint) else appoint
    if not remove_job(f'{aid}_finish'):
        if record_miss:
            logger.warning(f"预约{aid}取消时未发现计时器")
        return False

    remove_job(f'{aid}_start_ahead')

    if not remove_job(f'{aid}_start') and record_miss:
        logger.warning(f"预约{aid}取消时未发现开始计时器")
    if not remove_appoint_reminder(aid) and record_miss:
        logger.info(f"预约{aid}取消时未发现微信提醒")
    return True


@periodical('interval', minutes=30,
            start_date=datetime.now().replace(minute=3, second=0) + timedelta(hours=1))
def appoint_status_monitor():
    '''
    监控预约状态，若定时任务未执行可能会导致状态异常
    该函数定期进行检查并修复
    '''
    now = datetime.now()
    for appoint_id in Appoint.objects.filter(
        Astatus=Appoint.Status.APPOINTED, Astart__lt=now).values_list('pk', flat=True):
        try:
            start_appoint(appoint_id)
        except Exception as e:
            logger.error(f"Failed to start appoint {appoint_id} ({e})")

    now = datetime.now()
    for appoint_id in Appoint.objects.filter(
        Astatus=Appoint.Status.PROCESSING, Afinish__lt=now).values_list('pk', flat=True):
        try:
            finish_appoint(appoint_id)
        except Exception as e:
            logger.error(f"Failed to finish appoint {appoint_id} ({e})")
