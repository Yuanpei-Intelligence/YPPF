from collections import defaultdict
from typing import Callable, Optional, List
from datetime import datetime
from pandas import DataFrame

from dm.load_funcs import *
from dm.dump_funcs import *

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


def register_dump_groups(group: str, tasks: List[str]):
    """将任务加入组中
    """
    dump_groups[group].extend(tasks)


register_dump('page', PageTrackingDump)
register_dump('module', ModuleTrackingDump)
register_dump('appointment', AppointmentDump)
register_dump('org_activity', OrgActivityDump)
register_dump('person_position', PersonPosDump, accept_params=['year', 'semester'])
register_dump('person_activity', PersonActivityDump, accept_params=['year', 'semester'])

register_dump_groups('tracking', ['page', 'module'])
register_dump_groups('activity', ['org_activity', 'person_activity'])
register_dump_groups('underground', ['appointment'])
register_dump_groups('org', ['org_activity'])
register_dump_groups('person', ['person_position', 'person_activity', 'person_feedback', 'person_course'])

register_load('stu', load_stu, 'stuinf.csv')
register_load('orgtype', load_orgtype, 'orgtypeinf.csv')
register_load('org', load_org, 'orginf.csv')
register_load('orgtag', load_org_tag, 'orgtag.csv')
register_load('oldorgtags', load_old_org_tags, 'oldorgtags.csv')
register_load('help', load_help, 'help.csv')
