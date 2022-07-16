from django.core.management.base import BaseCommand, CommandParser, CommandError
from data_analysis.management import OutputFunc, load_map
from app.data_import import *

class Command(BaseCommand):
    help = '导入测试数据'

    def add_arguments(self, parser: CommandParser):
        # Positional arguments
        labels_help = ["要导入的模块, 所有的可导入模块有:"] + [x for x in load_map]
        parser.add_argument(
            'labels', nargs='+', type=str, 
            help=' '.join(labels_help)
        )
        # Optional arguments
        parser.add_argument(
            '-d', '--dir', type=str,
            help='测试数据文件所在的文件夹'
        )
        parser.add_argument(
            '-f', '--filename', type=str, nargs='+',
            help='测试数据文件名'
        )


    def handle(self, *args, **options):
        base_dir = options['dir'] if options['dir'] != None else ''
        labels = options['labels']
        if options['filename'] != None:
            files = options['filename']
            if (len(files) != len(labels)):
                raise CommandError('filename的个数必须和label的相同')
        else:
            files = ['' for _ in range(len(labels))]
        
        for label, filepath in zip(labels, files):
            self.stderr.write(f'Loading {label}')
            # 测试需要验证成功注册了函数，请删除下行
            try:
                load_function, default_path = load_map.get(label)
            except:
                raise CommandError(f"找不到Label {label}，请确认label为支持的导入数据选项！\
                    利用python manage.py load --help查看支持的导入数据选项。")
            if not filepath:
                filepath = default_path
            
            load_function(filepath, base_dir=base_dir, output_func=self.stderr.write)

            self.stderr.write(f'成功 load {label}')

