from collections import defaultdict
from typing import Callable, Optional, List
from datetime import datetime
from pandas import DataFrame

from data_analysis.load_funcs import *
from data_analysis.dump_funcs import *
from app.data_import import *

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
    dump_groups[group].extend(tasks)


register_dump('page', page_data)
register_dump('module', module_data)
register_dump('appointment', appointment_data)
register_dump('org_activity', org_activity_data)
register_dump('org_position', org_position_data)
register_dump('participants', participants_data)
register_dump('feedback', feedback_data)
register_dump('course', course_data)

register_dump_groups('tracking', ['page', 'module'])
register_dump_groups('activity', ['org_activity', 'participants'])
register_dump_groups('underground', ['appointment'])
register_dump_groups('org', ['org_activity', 'participants'])
register_dump_groups('person', ['participants', 'feedback', 'org_position', 'course'])

register_load('stu', load_stu, 'stuinf.csv')
register_load('freshman', load_freshman, 'freshman.csv')
register_load('orgtype', load_orgtype, 'orgtypeinf.csv')
register_load('org', load_org, 'orginf.csv')
register_load('orgtag', load_org_tag, 'orgtag.csv')
register_load('oldorgtags', load_old_org_tags, 'oldorgtags.csv')
register_load('activity', load_activity, 'activityinfo.csv')
register_load('transfer', load_transfer, 'transferinfo.csv')
register_load('notification', load_notification, 'notificationinfo.csv')
register_load('help', load_help, 'help.csv')
register_load('courserecord', load_course_record, 'coursetime.xlsx')
register_load('feedbackType', load_feedback_type, 'feedbacktype.csv')
register_load('feedback', load_feedback, 'feedbackinf.csv')
register_load('feedbackComments', load_feedback_comments, 'feedbackcomments.csv')