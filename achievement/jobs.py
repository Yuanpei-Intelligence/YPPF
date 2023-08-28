import json
from datetime import datetime

from achievement.api import *
from achievement.models import Achievement
from generic.models import User
from scheduler.adder import *
from scheduler.periodic import periodical

@periodical('cron', 'start_semester', month=9, day=1)
def start_fall_semester():
    '''在每年9月1日读取秋季开学日期'''
    with open('/workspace/config.json') as f:
        data = json.load(f)
    fall_semester_start = data['global']['semester_data']['fall_semester_start'].split('-')
    s_year = int(fall_semester_start[0])
    s_month = int(fall_semester_start[1])
    s_day = int(fall_semester_start[2])

    single_adder = ScheduleAdder(init_new_year, run_time=datetime(s_year, s_month, s_day))
    single_adder()


def init_new_year():
    '''触发 元气人生-开启大学第二、三、四年'''

    achievement_2 = Achievement.objects.get(name="开启大学生活第二年")
    user_list_2 = User.objects.get_enrollment_years().filter(utype='Student', active=True, enrollment_years=1)
    bulk_add_achievement_record(user_list=list(user_list_2), achievement=achievement_2)

    achievement_3 = Achievement.objects.get(name="开启大学生活第三年")
    user_list_3 = User.objects.get_enrollment_years().filter(utype='Student', active=True, enrollment_years=2)
    bulk_add_achievement_record(user_list=list(user_list_3), achievement=achievement_3)

    achievement_4 = Achievement.objects.get(name="开启大学生活第四年")
    user_list_4 = User.objects.get_enrollment_years().filter(utype='Student', active=True, enrollment_years=3)
    bulk_add_achievement_record(user_list=list(user_list_4), achievement=achievement_4)
