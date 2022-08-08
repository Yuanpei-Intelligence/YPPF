from collections import defaultdict
from typing import Callable, Optional, List
from datetime import datetime
from pandas import DataFrame

from data_analysis.load_funcs import *
from data_analysis.dump_funcs import *

load_map = {}
dump_map = {}
dump_groups = defaultdict(list)

# 类型提示
OutputFunc = Callable[[str], Optional[str]]
LoadFunc = Callable[[str, Optional[OutputFunc]], Optional[str]]

StartTime = EndTime = Optional[datetime]
HashFunc = Callable[[str], str]
DumpFunc = Callable[[StartTime, EndTime, Optional[HashFunc]], DataFrame]


def register_load(cmd_label: str, load_func: LoadFunc, default_path: str):
    """将导入函数注册到指令列表中
    """
    load_map[cmd_label] = load_func, default_path


def register_dump(task: str, dump_func: DumpFunc,
                  accept_params: list = ['start_time', 'end_time']):
    """将导出函数注册到指令列表中

    :param task: 任务名称，也用作导出文件的 sheet name
    :type task: str
    :param dump_func: 导出函数
    :type dump_func: DumpFunc
    :param accept_params: 导出函数接受的参数, defaults to ['start_time', 'end_time']
    :type accept_params: list, optional
    """
    dump_map[task] = dump_func, accept_params


def register_dump_groups(group: str, *tasks: str):
    """将任务加入组中
    """
    dump_groups.extend(tasks)


register_dump('page', page_data)
register_dump('module', module_data)
register_dump('appointment', appointment_data)
register_dump('org_activity', org_activity_data)
register_dump('org_position', org_position_data)
register_dump('participants', participants_data)
register_dump('feedback', feedback_data)

register_dump_groups('tracking', ['page', 'module'])
register_dump_groups('activity', ['org_activity', 'participants'])
register_dump_groups('underground', ['appointment'])
register_dump_groups('org', ['org_activity', 'org_position', 'participants', 'feedback'])
