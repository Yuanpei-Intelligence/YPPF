from django.core.management.base import BaseCommand

from yp_library.jobs import update_lib_data



class Command(BaseCommand):
    help = '同步书房信息'

    def handle(self, *args, **options):
        update_lib_data()
