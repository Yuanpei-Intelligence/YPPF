from django.core.management.base import BaseCommand, CommandParser, CommandError
from data_analysis.management import load_map
from app.data_import import *

class Command(BaseCommand):
    help = '导入测试数据'

    def add_arguments(self, parser: CommandParser):
        # Positional arguments
        parser.add_argument(
            'labels', nargs='+', type=str, 
            help='要导入的模块, 所有的可导入模块有: ' + ' '.join(load_map.keys())
        )
        # Optional arguments
        parser.add_argument(
            '-d', '--dir', type=str,
            default='test_data/',
            help='测试数据文件所在的文件夹',
        )
        parser.add_argument(
            '-f', '--filename', type=str, nargs='+',
            help='测试数据文件名',
        )


    def handle(self, *args, **options):
        base_dir = options['dir'] if options['dir'] is not None else ''
        labels = options['labels']
        if options['filename'] is not None:
            files = options['filename']
            if (len(files) != len(labels)):
                raise CommandError('filename的个数必须和labels相同')
        else:
            files = [''] * len(labels)
        
        for label, filepath in zip(labels, files):
            # 测试需要验证成功注册了函数，请删除下行
            try:
                load_function, default_path = load_map[label]
            except:
                raise CommandError(f'找不到标签{label}，使用-h参数查看所有合法标签')
            filepath = filepath or default_path
            
            self.stdout.write(f'正在加载{label}...')
            ret = load_function(base_dir + filepath, output_func=self.stdout.write)
            if ret:
                self.stdout.write(ret)

