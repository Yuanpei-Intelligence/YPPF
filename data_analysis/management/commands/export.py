"""
export.py

export命令提供以xlsx格式导出记录的功能
"""

from data_analysis.management import dump_map

import os
from datetime import datetime
import pandas as pd
from django.core.management.base import BaseCommand
from boottest.hasher import MySHA256Hasher


def valid_datetime(s: str) -> datetime:
    """判断输入的日期(str)是否合法，并转化成datetime

    Args:
        s (str): "YY-mm-dd-HH:MM"或"YY-mm-dd"格式日期

    Raises:
        ValueError: 日期不符合上述格式

    Returns:
        datetime: 处理后的开始/结束时间
    """    
    try: return datetime.strptime(s, "%Y-%m-%d")
    except: pass
    try: return datetime.strptime(s, "%Y-%m-%d-%H:%M")
    except: pass
    msg = '日期格式错误："{0}"，格式："YY-mm-dd-HH:MM"或"YY-mm-dd"'.format(s)
    raise ValueError(msg)


def filename_modifier(filename: str, taskname: str) -> str:
    """处理缺省的文件名和没有后缀的文件名

    Args:
        filename (str): 待处理的文件名
        taskname (str): 任务名称，用于寻找默认文件名

    Returns:
        str: 处理后的文件名
    """    
    if filename == '':
        # 如果是合并输出，使用'export + 时间戳'作为默认文件名
        if taskname == 'combine':
            filename = 'export ' + datetime.now().strftime("%Y-%m-%d")
        else:
            filename = dump_map[taskname][1]
    if filename.endswith(('.xlsx', '.xls')) is False:
        filename += '.xlsx'
    return filename


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('targets', type=str, nargs='+',
                            help="指定输出任务，all执行所有输出任务",
                            choices=['all'] + dump_map.keys())

        parser.add_argument('-c', '--combine', type=bool,
                            default=True, help='是否合并成一个文件输出')
        parser.add_argument('-f', '--file', type=str, nargs='+',
                            default=[], help='输出文件名')
        parser.add_argument('-s', '--starttime', type=valid_datetime,
                            default=None, help='开始时间，格式："YY-mm-dd-HH:MM"或"YY-mm-dd"')
        parser.add_argument('-e', '--endtime', type=valid_datetime,
                            default=None, help='结束时间，格式："YY-mm-dd-HH:MM"或"YY-mm-dd"')
        parser.add_argument('-m', '--mask', type=bool, default=True, help='是否数据脱敏')
        parser.add_argument('-S', '--salt', type=str,
                            default=str(os.urandom(8)), help='hash salt')

    def handle(self, *args, **options):
        # 设置哈希函数
        hash_func = None
        if options['mask'] is True:
            hash_func = MySHA256Hasher(options['salt']).encode

        # 检测指定的输出文件名与指定的输出对象数量是否一致，不足则补全
        tasks = options['targets']
        # 处理有all命令的情况
        if 'all' in options['targets']:
            tasks = list(dump_map.keys())
        export_files = len(tasks)
        if options['combine'] is True:
            export_files = 1
        if len(options['file']) < export_files:
            options['file'] += [''] * (export_files - len(options['file']))

        self.stdout.write("开始进行{}项导出任务：".format(len(tasks)))
        # 如果合并文件，则将DataFrame分别输出到一个xlsx的不同sheet中
        if options['combine'] is True:
            filename = filename_modifier(options['file'][0], 'combine')
            writer = pd.ExcelWriter(filename)
            for tsk in tasks:
                self.stdout.write("正在导出 {} 到 {}".format(tsk, filename))
                df = dump_map[tsk][0](options['starttime'], options['endtime'], hash_func)
                df.to_excel(writer, sheet_name=tsk)

        else:
            for tsk, filename in zip(tasks, options['file']):
                filename = filename_modifier(filename, tsk)
                writer = pd.ExcelWriter(filename)
                self.stdout.write("正在导出 {} 到 {}".format(tsk, filename))
                df = dump_map[tsk][0](options['starttime'], options['endtime'], hash_func)
                df.to_excel(writer)

        self.stdout.write("导出结束！")

