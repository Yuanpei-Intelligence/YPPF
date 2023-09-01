from datetime import datetime, time

from achievement.api import bulk_add_achievement_record
from achievement.models import Achievement
from achievement.utils import calculate_enrollment_years
from scheduler.adder import ScheduleAdder
from scheduler.periodic import periodical
from semester.api import next_semester


@periodical('cron', 'start_fall_semester', month=9, day=1)
def start_fall_semester():
    '''在每年9月1日读取秋季开学日期'''

    ScheduleAdder(init_new_year, run_time=datetime.combine(next_semester().start_date, time.min))()


def init_new_year():
    '''触发 元气人生-开启大学第二、三、四年'''

    achievement_2 = Achievement.objects.get(name="开启大学生活第二年")
    user_list_2 = calculate_enrollment_years(2)
    bulk_add_achievement_record(user_list=user_list_2, achievement=achievement_2)

    achievement_3 = Achievement.objects.get(name="开启大学生活第三年")
    user_list_3 = calculate_enrollment_years(3)
    bulk_add_achievement_record(user_list=user_list_3, achievement=achievement_3)

    achievement_4 = Achievement.objects.get(name="开启大学生活第四年")
    user_list_4 = calculate_enrollment_years(4)
    bulk_add_achievement_record(user_list=user_list_4, achievement=achievement_4)
