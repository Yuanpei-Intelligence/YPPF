"""Scheduler for executing jobs in background

The scheduler is unique and should not export to other modules.
This module is no longer a exposed interface, use other modules instead.

Attributes:
    scheduler (BackgroundScheduler): The scheduler instance,
        treat it as a BackgroundScheduler
    logger (Logger): Logger for scheduler

See Also:
    - :module:`scheduler.adder`
    - :module:`scheduler.periodic`
    - :module:`scheduler.cancel`
"""

import six
from threading import Event
from functools import update_wrapper

import rpyc
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore

from record.log.utils import get_logger
from scheduler.config import scheduler_config as CONFIG


# Custom handler
logger = get_logger('apscheduler')


class Scheduler:
    """
    A wrapper around `BackgroundScheduler`

    It won't execute the job.
    When adding the job to database, also try to wakeup the executor
    """

    def __init__(self, wrapped_schedule: BackgroundScheduler):
        self.wrapped_schedule = wrapped_schedule
        self.remote_scheduler: BackgroundScheduler | None = None
        self.remain_times = 3

    def __getattr__(self, name: str):
        target_method = getattr(self.wrapped_schedule, name)
        def wrapper(*args, **kwargs):
            val = target_method(*args, **kwargs)
            self.wakeup_executor()
            return val
        update_wrapper(wrapper, target_method)
        return wrapper

    def wakeup_executor(self):
        if self.remote_scheduler is None:
            self.connect_remote()
        if self.remote_scheduler is not None:
            self.remote_scheduler.wakeup()
        else:
            logger.warning('Remote scheduler not found, job may not be executed.')

    def connect_remote(self):
        if self.remain_times <= 0:
            return
        self.remain_times -= 1
        conn: rpyc.Connection = rpyc.connect(
            "localhost", CONFIG.rpc_port,
            config={"allow_all_attrs": True})
        self.remote_scheduler = conn.root


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


if CONFIG.use_scheduler:
    scheduler: BackgroundScheduler = Scheduler(start_scheduler())  # type: ignore
else:
    # Not start, no real_add_job
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_jobstore(DjangoJobStore(), "default")
