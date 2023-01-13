from django.core.management.base import BaseCommand, CommandParser, CommandError
from dm.management import load_map

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
            '-f', '--filenames', type=str, nargs='+',
            help='测试数据文件名',
        )


    def handle(self, *args, **options):
        base_dir = options['dir'] if options['dir'] is not None else ''
        labels = options['labels']
        if options['filenames'] is not None:
            filenames = options['filenames']
            if (len(filenames) != len(labels)):
                raise CommandError('filename的个数必须和labels相同')
        else:
            filenames = [''] * len(labels)
        
        for label, filepath in zip(labels, filenames):
            try:
                load_function, default_path = load_map[label]
            except:
                raise CommandError(f'找不到标签{label}，使用-h参数查看所有合法标签')
            filepath = filepath or default_path
            filepath = base_dir + filepath
            
            self.stdout.write(f'正在加载{label}...')
            ret = load_function(filepath, output_func=self.stdout.write)
            if ret:
                self.stdout.write(ret)
