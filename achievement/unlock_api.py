"""
本部分包含所有解锁成就相关的API
"""
from datetime import datetime

from generic.models import User
from achievement.models import Achievement
from achievement.api import trigger_achievement


__all__ = [
    'unlock_achievement',
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

""" 洁身自好 """

""" 严于律己 """

""" 五育并举 """

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
    achievement_income_dict = {
        '首次获得元气值': 1,
        '学期内获得10元气值': 10,
        '学期内获得30元气值': 30,
        '学期内获得50元气值': 50,
        '学期内获得100元气值': 100
    }
    achievement_expenditure_dict = {
        '首次消费元气值': 1,
        '学期内消费10元气值': 10,
        '学期内消费30元气值': 30,
        '学期内消费50元气值': 50,
        '学期内消费100元气值': 100
    }

    # 计算收支情况
    # TODO: 存在循环引用，暂时放在这里，后续改为信号控制的方式后可改回
    from app.YQPoint_utils import get_income_expenditure
    income, expenditure, has_records = get_income_expenditure(
        user, start_time, end_time)

    if has_records:
        for achievement_name in achievement_income_dict.keys():
            if income >= achievement_income_dict[achievement_name]:
                trigger_achievement(
                    user, Achievement.objects.get(name=achievement_name))
        for achievement_name in achievement_expenditure_dict.keys():
            if expenditure >= achievement_expenditure_dict[achievement_name]:
                trigger_achievement(
                    user, Achievement.objects.get(name=achievement_name))


""" 三五成群 """

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
