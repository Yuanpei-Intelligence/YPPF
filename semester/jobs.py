from datetime import datetime, time

from scheduler.adder import ScheduleAdder
from scheduler.periodic import periodical
from semester.api import next_semester


__all__ = [
    'register_new_school_year_jobs',
]


@periodical('cron', '注册新学年定时任务', month=9, day=1)
def register_new_school_year_jobs():
    '''在每年9月1日读取秋季开学日期'''
    ScheduleAdder(init_new_school_year, id='init_new_year', name='初始化新学年',
        run_time=datetime.combine(next_semester().start_date, time.min))()


def init_new_school_year():
    from achievement.jobs import new_school_year_achievements
    new_school_year_achievements()
    # TODO: Position renew, Credit Recover
