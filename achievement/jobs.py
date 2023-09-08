from datetime import date, timedelta

from scheduler.periodic import periodical
from achievement.models import Achievement
from achievement.utils import bulk_add_achievement_record, get_students_by_grade
from achievement.api import unlock_credit_achievements_by_name
from semester.api import current_semester


__all__ = [
    'unlock_credit_achievements',
    'new_school_year_achievements',
]


# 信用分相关成就激活判断 每月1日6点运行
@periodical('cron', job_id='解锁信用分成就', day=1, hour=6, minute=0)
def unlock_credit_achievements():
    semester = current_semester()
    today = date.today()
    last_month_lastday = today - timedelta(days=today.day)
    last_month_firstday = last_month_lastday.replace(day=1)
    DAYS_LIMIT = 21
    # 如果当前日期位于学期中间，进行'当月没有扣除信用分'成就的触发
    if semester.start_date <= today < semester.end_date: # 注意end_date是指放假开始的当天
        if (today - semester.start_date).days >= DAYS_LIMIT: # 上月最后一天距离学期初的天数超过阈值
            unlock_credit_achievements_by_name(last_month_firstday, last_month_lastday, '当月没有扣除信用分')
    # 如果当前日期位于学期结束后
    elif today >= semester.end_date:
        # 进行'一学期没有扣除信用分'成就的触发
        unlock_credit_achievements_by_name(semester.start_date, semester.end_date-timedelta(days=1), '一学期没有扣除信用分')
        # 进行'当月没有扣除信用分'成就的触发
        if last_month_firstday < semester.end_date:
            if (semester.end_date - last_month_firstday).days >= DAYS_LIMIT: # 上月第一天距离学期末的天数超过阈值
                unlock_credit_achievements_by_name(last_month_firstday, last_month_lastday, '当月没有扣除信用分')
    # 简单起见，不妨每年7月1日进行'一学年没有扣除信用分'成就触发
    if today.month == 7:
        unlock_credit_achievements_by_name(today-timedelta(days=365), today, '一学年没有扣除信用分')


def new_school_year_achievements():
    '''触发 元气人生-开启大学第二、三、四年'''
    for i, name in zip(range(2, 7), ['二', '三', '四', '五', '六']):
        achievement = Achievement.objects.get(name=f'开启大学生活第{name}年')
        bulk_add_achievement_record(get_students_by_grade(i), achievement)
