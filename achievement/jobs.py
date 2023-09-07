from datetime import date, timedelta

from scheduler.periodic import periodical
from achievement.models import Achievement
from achievement.utils import bulk_add_achievement_record, get_students_by_grade, get_students_without_credit_record
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
    # 如果当前日期位于学期中间，且距离学期开始已经过去21天以上，触发当月没有扣除信用分成就
    if semester.start_date <= today < semester.end_date: # 注意end_date是指放假开始的当天
        days = (today - semester.start_date).days # 上月最后一天距离学期初的天数
        if days >= 21:
            students = get_students_without_credit_record(last_month_firstday, last_month_lastday)
            achievement = Achievement.objects.get(name='当月没有扣除信用分')
            bulk_add_achievement_record(students, achievement)
    # 如果当前日期位于学期结束后
    elif today >= semester.end_date:
        # 进行'一学期没有扣除信用分'成就的触发
        students = get_students_without_credit_record(semester.start_date, semester.end_date-timedelta(days=1))
        achievement = Achievement.objects.get(name='一学期没有扣除信用分')
        bulk_add_achievement_record(students, achievement)
        # 如果上月中有超过21天位于学期内，同样进行'当月没有扣除信用分'成就的触发
        if last_month_firstday < semester.end_date:
            days = (semester.end_date - last_month_firstday).days # 上月第一天距离学期末的天数
            if days >= 21:
                students = get_students_without_credit_record(last_month_firstday, last_month_lastday)
                achievement = Achievement.objects.get(name='当月没有扣除信用分')
                bulk_add_achievement_record(students, achievement)
    # 简单起见，不妨每年7月1日进行'一学年没有扣除信用分'成就触发
    if today.month == 7:
        students = get_students_without_credit_record(today-timedelta(days=365), today)
        achievement = Achievement.objects.get(name='一学年没有扣除信用分')
        bulk_add_achievement_record(students, achievement)
    # 简单起见，不妨每年6月1日进行'本科均没有扣除信用分'成就触发
    if today.month == 6:
        # 筛选出过去四年未扣除信用分的本科生
        all_students = get_students_without_credit_record(today-timedelta(days=365*4), today)
        # 为方便起见 四、五、六年级的本科生都算作将要毕业
        students = all_students.filter(username__startswith=str(today.year-4)[2:]|str(today.year-5)[2:]|str(today.year-6)[2:])
        achievement = Achievement.objects.get(name='本科均没有扣除信用分')
        bulk_add_achievement_record(students, achievement)


# 开启大学生活第X年系列 更新时间暂时定在9.15
@periodical('cron', job_id='开启大学生活成就', month=9, day=15, hour=6, minute=0)
def new_school_year_achievements():
    '''触发 元气人生-开启大学第二、三、四年'''
    for i, name in zip(range(2, 7), ['二', '三', '四', '五', '六']):
        achievement = Achievement.objects.get(name=f'开启大学生活第{name}年')
        bulk_add_achievement_record(get_students_by_grade(i), achievement)
