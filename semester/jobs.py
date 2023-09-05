from datetime import datetime, time

from achievement.api import new_school_year_achievements
from scheduler.adder import ScheduleAdder
from scheduler.periodic import periodical
from semester.api import next_semester


@periodical('cron', 'register_new_school_year_jobs', 'start_fall_semester', month=9, day=1)
def register_new_school_year_jobs():
    '''在每年9月1日读取秋季开学日期'''

    ScheduleAdder(init_new_school_year, run_time=datetime.combine(
        next_semester().start_date, time.min))()


def init_new_school_year():
    new_school_year_achievements()
    # TODO: Position renew, Credit Recover
