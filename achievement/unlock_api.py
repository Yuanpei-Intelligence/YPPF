"""
本部分包含所有解锁成就相关的API
"""
from datetime import datetime

from generic.models import User, CreditRecord
from achievement.models import Achievement
from achievement.api import trigger_achievement
from app.models import CourseRecord, Course


__all__ = [
    'unlock_achievement',
    'unlock_Credit_achievements',
    'unlock_Course_achievements',
    'unlock_YQPoint_achievements',
    'unlock_signin_achievements',
]


# 一般情况直接调用此函数即可
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


""" 元气人生 """

""" 洁身自好 : 暂时不做 """

""" 严于律己 """


def unlock_Credit_achievements(user: User, date: datetime) -> None:
    """
    解锁成就 包含严于律己所有成就的判断
    暂未完成

    :param user: 要查询的用户
    :type user: User
    :param date: 当前日期
    :type date: datetime
    """
    # 当月没有扣除信用分
    records = CreditRecord.objects.filter(user=user)
    # 不知道怎么实现方便
    # 其实可以直接写一个command 周期性运行检验


""" 五育并举 """


def unlock_Course_achievements(user: User) -> None:
    """
    解锁成就 包含五育并举与学时相关的成就的判断
    这个不太清楚怎么调用合适 是专门写一个command(个人倾向) 还是写在view的homepage里面？

    :param user: 要查询的用户
    :type user: User
    """
    records = CourseRecord.objects.filter(person__person_id=user)
    if records:
        # 统计有效学时
        total_hours = 0
        for record in records:
            if record.invalid == False:
                total_hours += record.total_hours
        # 解锁成就
        ACHIEVEMENT_LIST = [
            ('完成一半书院学分要求', 32),
            ('完成全部书院学分要求', 64),
            ('超额完成一半书院学分要求', 96),
            ('超额完成一倍书院学分要求', 128)
        ]
        for achievement_name, achievement_bound in ACHIEVEMENT_LIST:
            if total_hours >= achievement_bound:
                trigger_achievement(
                    user, Achievement.objects.get(name=achievement_name))
        # 德智体美劳检验
        course_types = set(
            [record.course.CourseType for record in records if record.invalid == False])
        COURSE_DICT = {
            Course.CourseType.MORAL: '德育',
            Course.CourseType.INTELLECTUAL: "智育",
            Course.CourseType.PHYSICAL: "体育",
            Course.CourseType.AESTHETICS: "美育",
            Course.CourseType.LABOUR: "劳动教育"
        }
        for type in course_types:
            trigger_achievement(
                user, Achievement.objects.get(name='首次修习'+COURSE_DICT[type]+'课程'))


""" 志同道合 """


""" 元气满满 """


def unlock_YQPoint_achievements(user: User, start_time: datetime, end_time: datetime) -> None:
    """
    解锁成就 包含元气满满所有成就的判断

    :param user: 要查询的用户
    :type user: User
    :param start_time: 开始时间
    :type start_time: datetime
    :param end_time: 结束时间
    :type end_time: datetime
    """
    ACHIEVEMENT_INCOME_LIST = [
        ('首次获得元气值', 1),
        ('学期内获得10元气值', 10),
        ('学期内获得30元气值', 30),
        ('学期内获得50元气值', 50),
        ('学期内获得100元气值', 100)
    ]
    ACHIEVEMENT_EXPENDITURE_LIST = [
        ('首次消费元气值', 1),
        ('学期内消费10元气值', 10),
        ('学期内消费30元气值', 30),
        ('学期内消费50元气值', 50),
        ('学期内消费100元气值', 100)
    ]

    from app.YQPoint_utils import get_income_expenditure
    # 计算收支情况
    # TODO: 存在循环引用，暂时放在这里，后续改为信号控制的方式后可改回
    from app.YQPoint_utils import get_income_expenditure
    income, expenditure, has_records = get_income_expenditure(
        user, start_time, end_time)

    if has_records:
        for achievement_name, achievement_bound in ACHIEVEMENT_INCOME_LIST:
            if income >= achievement_bound:
                trigger_achievement(
                    user, Achievement.objects.get(name=achievement_name))
        for achievement_name, achievement_bound in ACHIEVEMENT_EXPENDITURE_LIST:
            if expenditure >= achievement_bound:
                trigger_achievement(
                    user, Achievement.objects.get(name=achievement_name))


""" 三五成群 : 全部外部录入 """

""" 智慧生活 """

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
    created = False
    achievement_dict = {
        '连续登录一周': 7,
        '连续登录一学期': 112,  # 一学期按16*7天算
        '连续登录一整年': 365,
    }
    for achievement_name in achievement_dict.keys():
        if continuous_days >= achievement_dict[achievement_name]:
            created = trigger_achievement(
                user, Achievement.objects.get(name=achievement_name))
    return created
