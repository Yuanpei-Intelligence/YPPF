'''
本部分包含所有解锁成就相关的API
'''
from datetime import datetime

from django.db.models import Sum

from generic.models import User
from app.models import CourseRecord, Course
from achievement.models import Achievement
from achievement.utils import trigger_achievement


__all__ = [
    'unlock_achievement',
    'unlock_course_achievements',
    'unlock_YQPoint_achievements',
    'unlock_signin_achievements',
]


def unlock_achievement(user: User, achievement_name: str) -> bool:
    '''
    解锁成就

    :param user: 要解锁的用户
    :type user: User
    :param achievement_name: 要解锁的成就名
    :type achievement_name: str
    :return: 是否成功解锁
    :rtype: bool
    '''
    return trigger_achievement(user, Achievement.objects.get(name=achievement_name))


def _unlock_by_value(user: User, acquired_value: float,
                     sorted_achievements: list[tuple[float, str]]) -> bool:
    '''将所有超过了解锁阈值的成就解锁'''
    created = False
    for bound, achievement_name in sorted_achievements:
        if acquired_value < bound:
            break
        created |= unlock_achievement(user, achievement_name)
    return created


''' 元气人生 '''

''' 洁身自好 : 暂时不做 '''

''' 严于律己 : 定时任务 '''

''' 五育并举 '''


def unlock_course_achievements(user: User) -> None:
    '''
    解锁成就 包含五育并举与学时相关的成就的判断
    这个不太清楚怎么调用合适 是专门写一个command(个人倾向) 还是写在view的homepage里面？

    :param user: 要查询的用户
    :type user: User
    '''
    records = CourseRecord.objects.filter(
        person__person_id=user, invalid=False)
    if not records:
        return

    # 统计有效学时
    total_hours = records.aggregate(
        total_hours=Sum('total_hours'))['total_hours']
    # 解锁成就
    _unlock_by_value(user, total_hours, [
        (32, '完成一半书院学分要求'),
        (64, '完成全部书院学分要求'),
        (96, '超额完成一半书院学分要求'),
        (128, '超额完成一倍书院学分要求'),
    ])

    # 德智体美劳检验
    course_types = set(records.values_list('course__type', flat=True))
    COURSE_DICT = {
        Course.CourseType.MORAL: '德育',
        Course.CourseType.INTELLECTUAL: '智育',
        Course.CourseType.PHYSICAL: '体育',
        Course.CourseType.AESTHETICS: '美育',
        Course.CourseType.LABOUR: '劳动教育',
    }
    for course_type in course_types:
        unlock_achievement(user, '首次修习' + COURSE_DICT[course_type] + '课程')


''' 志同道合 '''

''' 元气满满 '''


def unlock_YQPoint_achievements(user: User, start_time: datetime, end_time: datetime) -> None:
    '''
    解锁成就 包含元气满满所有成就的判断

    :param user: 要查询的用户
    :type user: User
    :param start_time: 开始时间
    :type start_time: datetime
    :param end_time: 结束时间
    :type end_time: datetime
    '''
    # 计算收支情况
    # TODO: 存在循环引用，暂时放在这里，后续改为信号控制的方式后可改回
    from app.YQPoint_utils import get_income_expenditure
    income, expenditure = get_income_expenditure(user, start_time, end_time)
    _unlock_by_value(user, income, [
        (1, '首次获得元气值'),
        (10, '学期内获得10元气值'),
        (30, '学期内获得30元气值'),
        (50, '学期内获得50元气值'),
        (100, '学期内获得100元气值'),
    ])
    _unlock_by_value(user, expenditure, [
        (1, '首次消费元气值'),
        (10, '学期内消费10元气值'),
        (30, '学期内消费30元气值'),
        (50, '学期内消费50元气值'),
        (100, '学期内消费100元气值'),
    ])


''' 三五成群 : 全部外部录入 '''

''' 智慧生活 '''

# 连续登录系列


def unlock_signin_achievements(user: User, continuous_days: int) -> bool:
    '''
    解锁成就
    智慧生活-连续登录一周/一学期/一整年

    :param user: 要解锁的用户
    :type user: User
    :return: 是否成功解锁
    :rtype: bool
    '''
    created = _unlock_by_value(user, continuous_days, [
        (7, '连续登录一周'),
        (7 * 16, '连续登录一学期'),
        (365, '连续登录一整年'),
    ])
    return created
