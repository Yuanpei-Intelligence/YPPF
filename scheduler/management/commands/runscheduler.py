from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore
import rpyc
from rpyc.utils.server import ThreadedServer

from utils.log import get_logger


EXECUTOR_PORT = settings.MY_RPC_PORT
TZ = settings.TIME_ZONE

logger = get_logger('apscheduler')


class SchedulerService(rpyc.Service):
    def __init__(self, scheduler: BackgroundScheduler):
        # It is OK to pass an instance of service to Threadserver now
        self.scheduler = scheduler

    def exposed_wakeup(self):
        return self.scheduler.wakeup()


class Command(BaseCommand):
    help = "Runs apscheduler."

    def handle(self, *args, **options):

        scheduler = BackgroundScheduler(timezone=TZ)
        scheduler.add_jobstore(DjangoJobStore(), "default")
        scheduler.start()

        protocol_config = {
            'allow_all_attrs': True,
            'logger': logger,
        }
        server = ThreadedServer(SchedulerService(scheduler),
                                port=EXECUTOR_PORT,
                                protocol_config=protocol_config)
        try:
            logger.info('Starting scheduler with executor')
            server.start()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            scheduler.shutdown()
