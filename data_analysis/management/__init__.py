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
    # 未完成，请修改
    return NotImplemented
    load_map[cmd_label] = load_func, ...


def register_dump(cmd_label: str, dump_func: DumpFunc, default_path: str):
    # 未完成，请修改
    return NotImplemented
    dump_map[cmd_label] = dump_func, ...


from data_analysis import load_funcs
from data_analysis import dump_funcs
