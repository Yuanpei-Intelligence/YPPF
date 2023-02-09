"""
scheduler.py: provide 

1. `scheduler` as a "client", 
2. `periodical` as a way to register periodical jobs
"""

import six
from typing import Callable, Dict, Any
from threading import Event
from functools import update_wrapper
from dataclasses import dataclass

import rpyc
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore

from utils.log import get_logger
from scheduler.config import scheduler_conf


# Custom handler
logger = get_logger('apscheduler')


class Scheduler():
    """
    A wrapper around `BackgroundScheduler`

    It won't execute the job.
    When adding the job to database, also try to wakeup the executor
    """

    def __init__(self, wrapped_schedule: BackgroundScheduler):
        self.wrapped_schedule = wrapped_schedule
        self.remote_scheduler = None
        self.remain_times = 3

    def __getattr__(self, name: str):
        target_method = getattr(self.wrapped_schedule, name)

        def wrapper(*args, **kwargs):
            target_method(*args, **kwargs)
            if self.remote_scheduler is None and self.remain_times > 0:
                self.remain_times -= 1
                self.remote_scheduler = rpyc.connect(
                    "localhost", scheduler_conf.rpc_port,
                    config={"allow_all_attrs": True}).root
            if self.remote_scheduler is not None:
                self.remote_scheduler.wakeup()
            else:
                logger.warning(
                    'Remote scheduler not found, job may not be executed.')
        update_wrapper(wrapper, target_method)
        return wrapper


@dataclass
class PeriodicalJob():
    """
    Wrap a function as a periodical job.
    Notice that it is not a callable.
    """
    function: Callable[[], None]
    job_id: str
    trigger: str
    tg_args: Dict[str, int]

    def run(self, *args: Any, **kwds: Any):
        self.function(*args, **kwds)


def periodical(trigger: str, job_id: str = '', **trigger_args):
    """Wrap a function into a periodical job.

    If `job_id` is not provided, use function name.

    :param trigger: 'cron' or 'interval'
    :type trigger: str
    """
    def wrapper(fn: Callable[[], None]) -> PeriodicalJob:
        return PeriodicalJob(fn, job_id or fn.__name__, trigger, trigger_args)
    return wrapper


def start_scheduler() -> BackgroundScheduler:
    """Return a background scheduler that can add job to database,
    but not actually run the job.
    """
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_jobstore(DjangoJobStore(), "default")
    scheduler._event = Event()  # type: ignore
    with scheduler._jobstores_lock:                                # type: ignore
        for alias, store in six.iteritems(scheduler._jobstores):   # type: ignore
            store.start(scheduler, alias)
    scheduler.state = 1  # STATE_RUNNING
    return scheduler


if scheduler_conf.use_scheduler:
    scheduler: BackgroundScheduler = Scheduler(
        start_scheduler())  # type: ignore
else:
    # Not start, no real_add_job
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_jobstore(DjangoJobStore(), "default")
