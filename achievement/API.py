'''成就系统 API
- 处理用户触发成就
- 后台批量添加成就
'''
from achievement.models import Achievement, AchievementUnlock
from generic.models import User

__all__ = [
    'trigger_achievement',
    'bulk_add_achievement_record'
]


def trigger_achievement(user: User, achievement: Achievement):
    """

    Args:
        user (User): 触发该成就的用户
        achievement (Achievement): 该成就

    Returns:
        若单条记录添加成功返回 AchievementUnlock 对象，若未建立成功返回 None
    """

    try:
        achievement_unlock = AchievementUnlock.objects.create(
            user=user, achievement=achievement)
    except Exception as e:
        return None

    return achievement_unlock


def bulk_add_achievement_record(record_list: list[dict]):
    """
    Args:
        record_list (list[dict]): 成就记录的列表，记录以字典形式传入
        ( dict: {"user": User, "achievement": Achievement, ……} )

    Returns:
        bool: 是否成功添加
        list[AchievementUnlock]: 添加的解锁记录列表（若未成功添加返回空列表）
    """

    unlock_record_list = []

    for record in record_list:
        user = record["user"]
        achievement = record["achievement"]
        assert isinstance(user, User) and isinstance(
            achievement, Achievement), (type(user), type(achievement))
        unlock_record_list.append(
            AchievementUnlock(user=user, achievement=achievement))

    try:
        AchievementUnlock.objects.bulk_create(unlock_record_list)
        success = True
    except Exception as e:
        success = False
        return success, []

    return success, unlock_record_list
