from datetime import datetime, time

from achievement.api import bulk_add_achievement_record
from achievement.models import Achievement
from achievement.utils import get_students_by_grade
from scheduler.adder import ScheduleAdder
from scheduler.periodic import periodical
from semester.api import next_semester


@periodical('cron', 'start_fall_semester', month=9, day=1)
def start_fall_semester():
    '''在每年9月1日读取秋季开学日期'''

    ScheduleAdder(init_new_year, run_time=datetime.combine(
        next_semester().start_date, time.min))()


def new_year_achievements():
    '''触发 元气人生-开启大学第二、三、四年'''
    for (i, j) in zip(range(2, 7), ['二', '三', '四', '五', '六']):
        achievement = Achievement.objects.get(name=f'开启大学生活第{j}年')
        user_list = get_students_by_grade(i)
        bulk_add_achievement_record(
            user_list=user_list, achievement=achievement)


def init_new_year():
    new_year_achievements()
