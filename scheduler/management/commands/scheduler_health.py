import rpyc
from django.core.management.base import BaseCommand

from scheduler.config import scheduler_config as CONFIG


class Command(BaseCommand):
    help = "get scheduler health status"

    def handle(self, *args, **options):
        conn = rpyc.connect("localhost", CONFIG.rpc_port)
        health = conn.root.health_check()
        conn.close()
        if health:
            print('status: running')
            exit(0)
        else:
            print('status: not running')
            exit(1)
