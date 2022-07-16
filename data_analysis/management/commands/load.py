from django.core.management.base import BaseCommand, CommandParser
from data_analysis.management import load_map

class Command(BaseCommand):
    help = 'NotImplemented'

    def add_arguments(self, parser: CommandParser):
        # Positional arguments
        parser.add_argument(
            'labels', nargs='+', type=str, help='要导入的模块'
        )
        parser.add_argument(
            '-d', '--dir', type=str,
            help='测试数据文件所在的文件夹'
        )
        parser.add_argument(
            '-f', '--filename', type=str,
            help='测试数据文件名'
        )


    def handle(self, *args, **options):
        for label in options['labels']:
            print(f'Loading {label} from ...')
            # 测试需要验证成功注册了函数，请删除下行
            self.stdout.write('filepath is test.csv')
            ...
