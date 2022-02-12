from django.conf import settings

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore

import rpyc
from rpyc.utils.server import ThreadedServer

import logging
logging.getLogger('apscheduler').setLevel(settings.__LOG_LEVEL)
logger = logging.getLogger(__name__)


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

        protocol_config = {
            'allow_all_attrs': True,
            'logger': logger,
        }
        server = ThreadedServer(SchedulerService(scheduler), port=settings.RPC_PORT, protocol_config=protocol_config)
        try:
            logging.info("Starting thread server...")
            server.start()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            scheduler.shutdown()

