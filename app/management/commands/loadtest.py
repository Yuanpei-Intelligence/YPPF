from argparse import HelpFormatter
from tokenize import group
from django.core.management.base import BaseCommand, CommandError, CommandParser
from app.data_import import *
from app.data_import import load_activity
from app.data_import import load_transfer
from app.data_import import load_notification
from app.data_import import load_freshman
from app.data_import import load_help

class LoadtestHandler:
    def __init__(self) -> None:
        self.loadFunc = {
            "loadStu": load_stu,
            "loadOrgType": load_orgtype,
            "loadOrg": load_org,
            "loadOrgTag": load_org_tag,
            "loadActivity": load_activity,
            "loadTransfer": load_transfer,
            "loadNotification": load_notification,
            "loadFreshman": load_freshman,
            "loadHelp": load_help,
            "loadCourseRecord": load_course_record,
            "loadFeedbackType": load_feedback_type,
            "loadFeedback": load_feedback,
            "loadFeedbackComments": load_feedback_comments
        }

class Command(BaseCommand):
    help = ''

    def add_arguments(self, parser: CommandParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '-a', '--all', action='store_true',
            help='导入test_data/文件夹下的所有数据'
        )
        group.add_argument(
            '-s', '--single-filename', action='store', type=str,
            help='导入单个文件的数据'
        )
        return super().add_arguments(parser)

    def handle(self, *args, **options):
        print(options)
