from typing import Callable, Optional
from datetime import datetime
from pandas import DataFrame

__all__ = [
    'register_load', 'register_dump',
]

load_map = {}
dump_map = {}

# 类型提示
OutputFunc = Callable[[str], Optional[str]]
LoadFunc = Callable[[str, Optional[OutputFunc]], Optional[str]]

StartTime = EndTime = Optional[datetime]
HashFunc = Callable[[str], str]
DumpFunc = Callable[[StartTime, EndTime, Optional[HashFunc]], DataFrame]


def register_load(cmd_label: str, load_func: LoadFunc, default_path: str):
    '''将导入函数注册到指令列表中'''
    load_map[cmd_label] = load_func, default_path


def register_dump(task: str, dump_func: DumpFunc,
                  accept_params: list = ['start_time', 'end_time']):
    dump_map[task] = dump_func, accept_params

from data_analysis import load_funcs
from data_analysis import dump_funcs
