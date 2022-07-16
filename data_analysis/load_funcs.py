from data_analysis.management import register_load

from app.data_import import *

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
