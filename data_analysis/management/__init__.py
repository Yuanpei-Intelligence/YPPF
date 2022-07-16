from typing import Callable, Optional
from datetime import datetime
from pandas import DataFrame
from app.data_import import *

__all__ = [
    'register_load', 'register_dump',
]

load_map = {
    "loadStu": (load_stu, 'stuinf.csv'),
    "loadOrgType": (load_orgtype, 'orgtypeinf.csv'),
    "loadOrg": (load_org, 'orginf.csv'),
    "loadOrgTag": (load_org_tag, 'orgtag.csv'),
    "loadActivity": (load_activity, 'activityinfo.csv'),
    "loadTransfer": (load_transfer, 'transferinfo.csv'),
    "loadNotification": (load_notification, 'notificationinfo.csv'),
    "loadFreshman": (load_freshman, 'freshmaninfp.csv'),
    "loadHelp": (load_help, 'help.csv'),
    "loadCourseRecord": (load_course_record, 'courserecord.csv'),
    "loadFeedbackType": (load_feedback_type, 'feedbacktype.csv'),
    "loadFeedback": (load_feedback, 'feedbackinf.csv'),
    "loadFeedbackComments": (load_feedback_comments, 'feedbackcomments.csv'),
}
dump_map = {}

# 类型提示
OutputFunc = Callable[[str], Optional[str]]
LoadFunc = Callable[[str, Optional[OutputFunc]], Optional[str]]

StartTime = EndTime = Optional[datetime]
HashFunc = Callable[[str], str]
DumpFunc = Callable[[StartTime, EndTime, Optional[HashFunc]], DataFrame]


def register_load(cmd_label: str, load_func: LoadFunc, default_path: str):
    load_map[cmd_label] = (load_func, default_path) 


def register_dump(cmd_label: str, dump_func: DumpFunc, default_path: str):
    # 未完成，请修改
    return NotImplemented
    dump_map[cmd_label] = dump_func, ...


from data_analysis import load_funcs
from data_analysis import dump_funcs
