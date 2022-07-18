"""
export.py

export命令提供以xlsx格式导出记录的功能
"""
import os

from data_analysis.management import dump_map

from datetime import datetime
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from random import randint
from hashlib import sha512


def valid_datetime(s: str) -> datetime:
    """判断输入的日期(str)是否合法，并转化成datetime"""
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d-%H:%M")
        except ValueError:
            msg = '日期格式错误："{0}"，格式："YY-mm-dd-HH:MM"或"YY-mm-dd"'.format(s)
            raise ValueError(msg)


def filename_modifier(filename: str, taskname: str) -> str:
    """处理缺省的文件名和没有后缀的文件名"""
    if filename == '':
        # 如果是合并输出，使用'export + 时间戳'作为默认文件名
        if taskname == 'combine':
            filename = 'export ' + datetime.now().strftime("%H:%M:%S")
        else:
            filename = dump_map[taskname][1]
    if filename[-5:] != '.xlsx' and filename[-4:] != '.xls':
        filename += '.xlsx'
    return filename


class HashClass:
    """本class定义了哈希化的函数，"""
    def __init__(self, salt: str = ''):
        self.salt = salt

    def hash_func(self, s: str) -> str:
        """采用sha512进行哈希化，可修改"""
        return sha512((s + self.salt).encode('utf-8')).hexdigest()


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
            hash_func = HashClass(options['salt']).hash_func

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

