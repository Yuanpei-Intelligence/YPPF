import os
import logging
import rpyc
from rpyc.utils.server import ThreadedServer

from django.core.management.base import BaseCommand
from django.conf import settings

from yp_library.management.sync import *


logger = logging.getLogger(__name__)
logger.setLevel(settings.MY_LOG_LEVEL)
fh = logging.FileHandler(os.path.join(settings.MY_LOG_DIR, 'lib_fetch.log'))
fh.setLevel(settings.MY_LOG_LEVEL)
logger.addHandler(fh)


class LibService(rpyc.Service):

    def exposed_update(self):
        logger.info('尝试拉取书房数据库......')
        update_reader()
        update_book()
        update_records()


class Command(BaseCommand):
    help = '同步书房信息'

    def handle(self, *args, **options):

        protocol_config = {
            'allow_all_attrs': True,
            'logger': logger,
        }
        server = ThreadedServer(LibService, port=settings.MY_LIB_RPC_PORT, protocol_config=protocol_config)
        try:
            server.start()
        except (KeyboardInterrupt, SystemExit):
            pass