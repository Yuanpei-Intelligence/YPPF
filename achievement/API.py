'''成就系统 API
- 处理用户触发成就
- 后台批量添加成就
'''
from achievement.models import Achievement, AchievementUnlock
from generic.models import User
from utils.global_messages import wrong

__all__ = [
    'trigger_achievement',
    'bulk_add_achievement_record'
]


def trigger_achievement(user: User, achievement: Achievement):

    try:
        achievement_unlock = AchievementUnlock.objects.create(
            user=user, achievement=achievement)
    except Exception as e:
        return wrong(str(e))

    return achievement_unlock


def bulk_add_achievement_record(record_list: list[dict]):
    """

    Args:
        record_list (list[dict]): 成就记录的列表，记录以字典形式传入
        ( dict: {"user": [User], "achievement": [achievement], ……} )

    Returns:
        bool: 是否成功添加
        list[AchievementUnlock]: 添加的解锁记录列表
    """
    success = True
    unlock_record_list = []
    for record in record_list:
        user = record["user"]
        achievement = record["achievement"]

        assert isinstance(user, User) and isinstance(
            achievement, Achievement), (type(user), type(achievement))

        try:
            achievement_unlock = AchievementUnlock.objects.create(
                user=user, achievement=achievement)
            unlock_record_list.append(achievement_unlock)
        except Exception as e:
            success = False
            return wrong(str(e))

    return success, unlock_record_list
