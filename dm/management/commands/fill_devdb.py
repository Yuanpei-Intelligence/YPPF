from django.core.management.base import BaseCommand

from dm.management.fake_records import create_all


class Command(BaseCommand):
    help = 'Populate dev db for test & development'

    def handle(self, *args, **options):
        print('Trying to fill dev database with fake records...')
        create_all()
