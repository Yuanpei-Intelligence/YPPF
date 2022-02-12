import os
import rpyc
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from apscheduler.events import SchedulerEvent, EVENT_SCHEDULER_START
import six
from threading import Event
import logging

class Scheduler():

    def __init__(self, wrapped_schedule, remote_scheduler):
        self.wrapped_schedule = wrapped_schedule
        self.remote_scheduler = remote_scheduler
    
    # def wakeup(self):
    #     self.remote_scheduler.wakeup()

    def __getattr__(self, name):
        # self.remote_scheduler.wakeup()
        target_method = getattr(self.wrapped_schedule, name)
        def wrapper(*args, **kwargs):
            target_method(*args, **kwargs)
            self.remote_scheduler.wakeup()
        wrapper.__name__ = target_method.__name__
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

def register_periodic_job(func, trigger='interval', *args, **kwargs):
    scheduler.add_job(func, trigger, id=func.__name__, *args, **kwargs)

if settings.__ENV in ["PRODUCT", "TEST"]:
    port_number = settings.RPC_PORT
    import time
    for i in range(3):
        try:
            remote_scheduler = rpyc.connect("localhost", port_number, config={"allow_all_attrs": True}).root
            break
        except:
            time.sleep(1)
    scheduler = Scheduler(start_scheduler(), remote_scheduler)
    logging.info("connect to remote scheduler server")
elif settings.__ENV in ["SCHEDULER"]:
    # 不理解为什么跑 command 也会调到 views.py
    # 总之必须定义一个 scheduler 但不会被真正使用到
    scheduler = None
else:
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_jobstore(DjangoJobStore(), "default")
    # If you do not want to run the scheduler, annotate the next line
    logging.info("start scheduler with executor")
    scheduler.start()




