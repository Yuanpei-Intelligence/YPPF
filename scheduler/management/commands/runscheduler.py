from django.conf import settings

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore

import rpyc
from rpyc.utils.server import ThreadedServer

import logging
logging.getLogger('apscheduler').setLevel(settings.MY_LOG_LEVEL)
logger = logging.getLogger(__name__)


from app.scheduler_func import *
from Appointment.utils.scheduler_func import clear_appointments

class SchedulerService(rpyc.Service):

    def __init__(self, scheduler):
        # It is OK to pass an instance of service to Threadserver now
        self.scheduler = scheduler

    def exposed_wakeup(self):
        return self.scheduler.wakeup()


class Command(BaseCommand):
    help = "Runs apscheduler."

    def handle(self, *args, **options):

        scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")
        scheduler.start()

        scheduler.add_job(get_weather,
                          'interval',
                          id='get_weather',
                          minutes=5,
                          replace_existing=True)
        scheduler.add_job(changeAllActivities,
                          'interval',
                          id='activityStatusUpdater',
                          minutes=5,
                          replace_existing=True)
        scheduler.add_job(clear_appointments,
                          'cron',
                          id='ontime_delete',
                          day_of_week='sat',
                          hour=3,
                          minute=30,
                          second=0,
                          replace_existing=True)
        scheduler.add_job(update_active_score_per_day,
                          "cron",
                          id='active_score_updater',
                          hour=1,
                          replace_existing=True)
        scheduler.add_job(longterm_launch_course,
                            "interval",
                            id="courseWeeklyActivitylauncher",
                            minutes=5,
                            replace_existing=True)
        scheduler.add_job(public_feedback_per_hour,
                          "cron",
                          id='feedback_public_updater',
                          minute=5,
                          replace_existing=True)

        protocol_config = {
            'allow_all_attrs': True,
            'logger': logger,
        }
        server = ThreadedServer(SchedulerService(scheduler), port=settings.MY_RPC_PORT, protocol_config=protocol_config)
        try:
            # logging.info("Starting thread server...")
            server.start()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            scheduler.shutdown()

