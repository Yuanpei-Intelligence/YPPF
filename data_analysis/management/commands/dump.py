import os
from typing import List
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


def complete_filename(filename: str = None) -> str:
    """
    处理缺省的文件名和没有后缀的文件名

    :param filename: 待处理的文件名, defaults to None
    :type filename: str, optional
    :return: 处理后的文件名
    :rtype: str
    """
    filename = (
        filename if filename is not None else
        datetime.now().strftime('%Y年%m月%d日') + MySHA256Hasher('').encode(
            datetime.now().strftime(' %H:%M:%S.%f'))[:4]
    )
    if not filename.endswith(('.xlsx', '.xls')):
        filename += '.xlsx'
    return filename


def extend_group_label(labels: List[str], extend_dict: dict) -> set:
    """Extend label to low-level, atomic tasks.
    Currently no support to recur

    :param labels: labels to be extended
    :type labels: List[str]
    :param extend_dict: ...
    :type extend_dict: dict
    :return: set of atomic tasks
    :rtype: set
    """
    tasks = []
    for label in labels:
        if label in extend_dict:
            tasks.extend(extend_dict[label])
        else:
            tasks.append(label)
    return tasks


class Command(BaseCommand):
    help = '导出数据'

    def add_arguments(self, parser):
        parser.add_argument('tasks', type=str, nargs='+',
                            help='Specify dumping task. Use all to execute all.',
                            choices=['all'] + list(dump_map.keys()) + list(dump_groups.keys()))
        parser.add_argument('-x', '--exclude', type=str, nargs='+',
                            help='exclude tasks')
        parser.add_argument('-d', '--dir', type=str, help='Dumping directory.',
                            default='test_data')
        parser.add_argument('-f', '--filename', type=str,
                            help='Dumping file name.')
        parser.add_argument('-s', '--start-time', type=valid_datetime,
                            help='Start time. Format: YY-mm-dd-HH:MM or YY-mm-dd')
        parser.add_argument('-e', '--end-time', type=valid_datetime,
                            help='End time. Format: YY-mm-dd-HH:MM or YY-mm-dd')
        parser.add_argument('-ay', '--year', type=int, help='Academic Year')
        parser.add_argument('-as', '--semester', type=str, help='Semester',
                            choices=['Fall', 'Spring', 'Fall+Spring'])
        parser.add_argument('-ex', '--extra', type=str,
                            help='Extra parameters')
        parser.add_argument('-m', '--mask', type=bool,
                            default=True, help='Mask student id.')
        parser.add_argument('-S', '--salt', type=str, help='hash salt')

    def handle(self, *args, **options):
        hash_func = (MySHA256Hasher(options['salt'] or str(os.urandom(8))).encode
                     if options['mask'] else None)
        tasks = list(dump_map.keys()) if 'all' in options['tasks'] else extend_group_label(
            options['tasks'], dump_groups)
        if options['exclude'] is not None:
            for label in extend_group_label(options['exclude'], dump_groups):
                if label in tasks:
                    tasks.remove(label)
        filename = complete_filename(options['filename'])
        filepath = os.path.join(options['dir'], filename)
        with pd.ExcelWriter(filepath) as writer:
            for task in tasks:
                dump_cls, accept_params = dump_map[task]
                self.stdout.write(f'正在导出 {task} 到 {filepath}')
                df: pd.DataFrame = dump_cls.dump(
                    hash_func=hash_func,
                    **{k: options[k] for k in set(accept_params).intersection(options.keys())}
                )
                df.to_excel(writer, sheet_name=task, index=False)
        self.stdout.write(f'导出结束！已导出至 {filepath}')
