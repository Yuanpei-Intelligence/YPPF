import os
import pandas as pd
from datetime import datetime

from django.core.management.base import BaseCommand

from boottest.hasher import MySHA256Hasher
from data_analysis.management import dump_map, dump_groups


def valid_datetime(s: str) -> datetime:
    """Generate valid datetime from str

    :param s: time str
    :type s: str
    :raises ValueError: Unexpected time format
    :return: datetime
    :rtype: datetime
    """
    try:
        return datetime.strptime(s, '%Y-%m-%d')
    except:
        pass
    try:
        return datetime.strptime(s, '%Y-%m-%d-%H:%M')
    except:
        pass
    msg = '日期格式错误："{0}"，格式："YY-mm-dd-HH:MM"或"YY-mm-dd"'.format(s)
    raise ValueError(msg)


def complete_filename(filename: str=None) -> str:
    '''
    处理缺省的文件名和没有后缀的文件名

    :param filename: 待处理的文件名, defaults to None
    :type filename: str, optional
    :return: 处理后的文件名
    :rtype: str
    '''
    filename = (
        filename if filename is not None else
        datetime.now().strftime('%Y年%m月%d日') + MySHA256Hasher('').encode(
            datetime.now().strftime(' %H:%M:%S.%f'))[:4]
    )
    if not filename.endswith(('.xlsx', '.xls')):
        filename += '.xlsx'
    return filename


class Command(BaseCommand):
    help = '导出数据'

    def add_arguments(self, parser):
        parser.add_argument('tasks', type=str, nargs='+',
                            help='Specify dumping task. Use all to execute all.',
                            choices=['ALL', 'EXCEPT'] + list(dump_map.keys()))
        parser.add_argument('-d', '--dir', type=str, help='Dumping directory.',
                            default='test_data')
        parser.add_argument('-f', '--filename', type=str, help='Dumping file name.')
        parser.add_argument('-s', '--start-time', type=valid_datetime,
                            help='Start time. Format: YY-mm-dd-HH:MM or YY-mm-dd')
        parser.add_argument('-e', '--end-time', type=valid_datetime,
                            help='End time. Format: YY-mm-dd-HH:MM or YY-mm-dd')
        parser.add_argument('-ay', '--year', type=int, help='Academic Year')
        parser.add_argument('-as', '--semester', type=str, help='Semester',
                            choices=['Fall', 'Spring', 'Fall+Spring'])
        parser.add_argument('-ex', '--extra', type=str, help='Extra parameters')
        parser.add_argument('-m', '--mask', type=bool,
                            default=True, help='Mask student id.')
        parser.add_argument('-S', '--salt', type=str, help='hash salt')


    def handle(self, *args, **options):
        hash_func = (MySHA256Hasher(options['salt'] or str(os.urandom(8))).encode
                     if options['mask'] else None)

        tasks: list = []
        except_flag = False
        # 预处理
        # 可优化，但数据规模导致没有意义
        for task in options['tasks']:
            if task == 'ALL':
                except_flag = False
                tasks.clear()
                tasks.extend(dump_map.keys())
            elif task in dump_groups.keys():
                # 预定义的标签组
                except_flag = False
                task_set = set(task)
                tasks.extend([t for t in dump_groups[task]
                              if t not in task_set and t in dump_map.keys()])
            elif task == 'EXCEPT':
                except_flag = True
            elif except_flag:
                try: tasks.remove(task)
                except: self.stderr.write(f'{task} 不是一个待导出的标签！')
            elif task not in tasks:
                tasks.append(task)
        # 文件路径
        filename = complete_filename(options['filename'])
        filepath = os.path.join(options['dir'], filename)
        with pd.ExcelWriter(filepath) as writer:
            for task in tasks:
                dump_function, accept_params = dump_map[task]
                self.stdout.write(f'正在导出 {task} 到 {filepath}')
                df: pd.DataFrame = dump_function(
                    hash_func=hash_func,
                    **{k: options[k] for k in set(accept_params).intersection(options.keys())}
                )
                df.to_excel(writer, sheet_name=task, index=False)
        self.stdout.write(f'导出结束！已导出至 {filepath}')
