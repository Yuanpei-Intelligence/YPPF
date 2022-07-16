from management import register_load
from app.data_import import *
LOAD_LIST = [
    ("stu", load_stu, 'stuinf.csv'),
    ("orgType", load_orgtype, 'orgtypeinf.csv'),
    ("org", load_org, 'orginf.csv'),
    ("orgTag", load_org_tag, 'orgtag.csv'),
    ("activity", load_activity, 'activityinfo.csv'),
    ("transfer", load_transfer, 'transferinfo.csv'),
    ("notification", load_notification, 'notificationinfo.csv'),
    ("freshman", load_freshman, 'freshmaninfp.csv'),
    ("help", load_help, 'help.csv'),
    ("courseRecord", load_course_record, 'courserecord.csv'),
    ("feedbackType", load_feedback_type, 'feedbacktype.csv'),
    ("feedback", load_feedback, 'feedbackinf.csv'),
    ("feedbackComments", load_feedback_comments, 'feedbackcomments.csv'),
]

for label, load_func, defaule_path in LOAD_LIST:
    register_load(label, load_func, defaule_path)