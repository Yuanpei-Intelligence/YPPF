from django.core.management.base import BaseCommand
from data_analysis.management import load_map

class Command(BaseCommand):
    help = NotImplemented

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('labels', nargs='+', type=str)

    def handle(self, *args, **options):
        for label in options['labels']:
            print(f'Loading {label} from ...')
            # 测试需要验证成功注册了函数，请删除下行
            self.stdout.write('filepath is test.csv')
            ...
