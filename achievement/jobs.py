import json
from datetime import datetime

from achievement.api import *
from achievement.models import Achievement
from generic.models import User
from scheduler.periodic import periodical
from scheduler.cancel import remove_job

@periodical('cron', 'start_semester', month=9, day=1)
def start_semester():
    '''在每年9月1日读取开学日期'''
    with open('/workspace/config_template.json') as f:
        data = json.load(f)
    semester_start = data['underground']['semester_data']['semester_start'].split('-')
    s_month = semester_start[1]
    s_day = semester_start[2]

    remove_job('second_year')

    @periodical('cron', 'second_year', month=s_month, day=s_day)
    def second_year():
        '''触发 元气人生-开启大学第二年'''
        achievement = Achievement.objects.get(name="开启大学第二年")
        user_list = User.objects.get_enrollment_years().filter(utype='Student', active=True, enrollment_years=1)
    
        bulk_add_achievement_record(user_list=list(user_list), achievement=achievement)

    return second_year()
    
