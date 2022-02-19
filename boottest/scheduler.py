import os
import rpyc
import six
import logging
from threading import Event
from functools import update_wrapper

from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore

from boottest import base_get_setting

class Scheduler():

    def __init__(self, wrapped_schedule):
        self.wrapped_schedule = wrapped_schedule
        self.remote_scheduler = None
        self.remain_times = 3

    def __getattr__(self, name):
        target_method = getattr(self.wrapped_schedule, name)
        def wrapper(*args, **kwargs):
            target_method(*args, **kwargs)
            if self.remote_scheduler is None and self.remain_times > 0:
                self.remain_times -= 1
                self.remote_scheduler = rpyc.connect(
                    "localhost", settings.MY_RPC_PORT,
                    config={"allow_all_attrs": True}).root
            if self.remote_scheduler is not None:
                self.remote_scheduler.wakeup()
            else:
                logging.warning('remote scheduler not found, job may not be executed.')
        update_wrapper(wrapper, target_method)
        return wrapper


def start_scheduler():

    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_jobstore(DjangoJobStore(), "default")
    if scheduler._event is None or scheduler._event.is_set():
        scheduler._event = Event()

    scheduler._check_uwsgi()

    with scheduler._jobstores_lock:

        # Start all the job stores
        for alias, store in six.iteritems(scheduler._jobstores):
            store.start(scheduler, alias)

        # Schedule all pending jobs
        for job, jobstore_alias, replace_existing in scheduler._pending_jobs:
            scheduler._real_add_job(job, jobstore_alias, replace_existing)
        del scheduler._pending_jobs[:]

    scheduler.state = 1 # STATE_RUNNING

    return scheduler

if base_get_setting("use_scheduler", bool, False, raise_exception=False):
    scheduler = Scheduler(start_scheduler())
else:
    # No real_add_job
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_jobstore(DjangoJobStore(), "default")
