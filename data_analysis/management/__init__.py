from collections import defaultdict
from typing import Callable, Optional
from datetime import datetime
from pandas import DataFrame

__all__ = [
    'register_load', 'register_dump',
]

load_map = {}
dump_map = defaultdict(list)

# 类型提示
OutputFunc = Callable[[str], Optional[str]]
LoadFunc = Callable[[str, Optional[OutputFunc]], Optional[str]]

StartTime = EndTime = Optional[datetime]
HashFunc = Callable[[str], str]
DumpFunc = Callable[[StartTime, EndTime, Optional[HashFunc]], DataFrame]


def register_load(cmd_label: str, load_func: LoadFunc, default_path: str):
    '''将导入函数注册到指令列表中'''
    load_map[cmd_label] = load_func, default_path


def register_dump(task: str, dump_func: DumpFunc, default_path: str, accept_params: list):
    dump_map[task].append((dump_func, default_path, accept_params))

from data_analysis import load_funcs
from data_analysis import dump_funcs
