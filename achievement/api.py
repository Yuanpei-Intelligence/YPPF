'''成就系统 API
- 处理用户触发成就
- 后台批量添加成就
'''
from achievement.models import Achievement, AchievementUnlock
from achievement.utils import get_students_by_grade
from generic.models import User
from utils.wrap import return_on_except

__all__ = [
    'trigger_achievement',
    'bulk_add_achievement_record',
]


@return_on_except(None, Exception, merge_type=True)
def trigger_achievement(user: User, achievement: Achievement) -> AchievementUnlock:
    '''处理用户触发成就，添加单个解锁记录

    Args:
    - user (User): 触发该成就的用户
    - achievement (Achievement): 该成就

    Returns:
    若单条记录添加成功返回 AchievementUnlock 对象，若未建立成功返回 None
    '''

    achievement_unlock = AchievementUnlock.objects.create(
        user=user, achievement=achievement)

    return achievement_unlock


@return_on_except(False, Exception)
def bulk_add_achievement_record(user_list: list[User], achievement: Achievement):
    '''批量添加成就解锁记录

    Args:
    - user_list (list[User]): 需批量添加的用户列表
    - achievement (Achievement): 需添加的成就

    Returns:
    - bool: 是否成功添加
    '''

    unlock_record_list = []
    users_with_achievement = AchievementUnlock.objects.filter(
        achievement=achievement).values_list('user', flat=True)

    for user in user_list:
        if user.pk not in users_with_achievement:  # 去除已获得过该成就的用户
            unlock_record_list.append(AchievementUnlock(
                user=user, achievement=achievement))

    AchievementUnlock.objects.bulk_create(unlock_record_list)

    return True


def new_school_year_achievements():
    '''触发 元气人生-开启大学第二、三、四年'''
    for (i, j) in zip(range(2, 7), ['二', '三', '四', '五', '六']):
        achievement = Achievement.objects.get(name=f'开启大学生活第{j}年')
        user_list = get_students_by_grade(i)
        bulk_add_achievement_record(
            user_list=user_list, achievement=achievement)
