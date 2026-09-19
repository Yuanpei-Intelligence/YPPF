"""生日祝福投放 - 审核提醒的定时任务调度。

进入等待审核后，为一审管理员预排提醒任务；一审通过后撤回一审任务并为
二审管理员排计划；通过或驳回后撤回对应阶段的剩余任务。
"""
import logging
from datetime import datetime, time as dt_time, timedelta

from scheduler.adder import ScheduleAdder
from scheduler.cancel import remove_job
from scheduler.scheduler import scheduler

from birthboard.models import BirthboardRecord

logger = logging.getLogger(__name__)

__all__ = [
    'schedule_first_approval_reminders',
    'schedule_second_approval_reminders',
    'cancel_approval_reminders',
]

_JOB_PREFIX = 'birthboard_approve_remind'


def _job_id(record_id: int, stage: str, run_time: datetime) -> str:
    return f'{_JOB_PREFIX}_{record_id}_{stage}_{run_time:%Y%m%d%H%M}'


def _at(day, hour: int) -> datetime:
    """组合日期与整点时刻，返回 naive 本地 datetime。"""
    return datetime.combine(day, dt_time(hour))


def _first_reminder_times(record: BirthboardRecord, now: datetime) -> list[datetime]:
    """一审提醒时刻：D-5/D-4 每天 9:00、14:00；D-3~D-1 每天 9:00~23:00 每小时。"""
    times: list[datetime] = []
    d = record.date
    for offset in (5, 4):
        for hour in (9, 14):
            times.append(_at(d - timedelta(days=offset), hour))
    for offset in (3, 2, 1):
        for hour in range(9, 24):
            times.append(_at(d - timedelta(days=offset), hour))
    return [t for t in times if t > now]


def _second_reminder_times(record: BirthboardRecord, now: datetime) -> list[datetime]:
    """二审提醒时刻：D-2 9:00、14:00 + D-1 9:00~23:00 每小时。

    只保留当前时间之后的时刻（进入二审较晚时，过去的时间点自动跳过）。
    """
    times: list[datetime] = []
    d = record.date
    for hour in (9, 14):
        times.append(_at(d - timedelta(days=2), hour))
    for hour in range(9, 24):
        times.append(_at(d - timedelta(days=1), hour))
    return [t for t in times if t > now]


def _send_approval_reminder(record_id: int, stage: str):
    """定时任务执行体：重新查库，仅当记录仍处该阶段待审核时才发送。"""
    from birthboard.notify import notify_approval_reminder

    record = BirthboardRecord.objects.filter(id=record_id).first()
    if record is None or record.status != BirthboardRecord.Status.WAITING_APPROVE:
        return
    if stage == 'first' and record.first_approved:
        return
    if stage == 'second' and (not record.first_approved or record.second_approver is not None):
        return
    notify_approval_reminder(record, stage)


def _schedule(record: BirthboardRecord, stage: str, times) -> None:
    for run_time in times:
        try:
            ScheduleAdder(
                _send_approval_reminder,
                id=_job_id(record.id, stage, run_time),
                run_time=run_time,
            )(record.id, stage)
        except Exception:
            logger.exception(
                'birthboard approval reminder schedule failed '
                'record_id=%s stage=%s time=%s',
                record.id, stage, run_time,
            )


def schedule_first_approval_reminders(record: BirthboardRecord) -> None:
    """进入等待审核后，预排一审提醒任务。"""
    _schedule(record, 'first', _first_reminder_times(record, datetime.now()))


def schedule_second_approval_reminders(record: BirthboardRecord) -> None:
    """一审通过后，预排二审提醒任务。"""
    _schedule(record, 'second', _second_reminder_times(record, datetime.now()))


def cancel_approval_reminders(record: BirthboardRecord, stage: str | None = None) -> None:
    """撤回某记录尚未触发的审核提醒任务；stage 为空时撤回全部阶段。"""
    prefix = f'{_JOB_PREFIX}_{record.id}_'
    if stage:
        prefix += f'{stage}_'
    try:
        for job in scheduler.get_jobs():
            if job.id.startswith(prefix):
                remove_job(job.id)
    except Exception:
        logger.exception(
            'birthboard approval reminder cancel failed record_id=%s stage=%s',
            record.id, stage,
        )
