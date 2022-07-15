from django.core.management.base import BaseCommand
from data_analysis.management import dump_map

class Command(BaseCommand):
    help = NotImplemented

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('labels', nargs='+', type=str)

    def handle(self, *args, **options):
        for label in options['labels']:
            # remember to handle 'all' label
            print(f'Dumping {label} into ...')
            ...
