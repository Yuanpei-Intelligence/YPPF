from django.core.management.base import BaseCommand

from yp_library.management.sync import *



class Command(BaseCommand):
    help = '同步书房信息'

    def handle(self, *args, **options):
        update_reader()
        update_book()
        update_records()
