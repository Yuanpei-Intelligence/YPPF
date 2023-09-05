'''成就系统 API
- 处理用户触发成就
- 后台批量添加成就
'''
from django.db.models import QuerySet

from achievement.models import Achievement, AchievementUnlock
from generic.models import User
from utils.wrap import return_on_except
from app.YQPoint_utils import YQPointRecord
from app.notification_utils import Notification, notification_create, bulk_notification_create


__all__ = [
    'trigger_achievement',
    'bulk_add_achievement_record',
]


@return_on_except(False, Exception)
def trigger_achievement(user: User, achievement: Achievement) -> bool:
    '''
    处理用户触发成就，添加单个解锁记录
    若已解锁则不添加
    按需发布通知与发放元气值奖励

    Args:
    - user (User): 触发该成就的用户
    - achievement (Achievement): 该成就

    Returns:
    - bool: 是否成功解锁

    Warning:
        本函数不保证原子化，仅保证并行安全性，但该实现存在风险
    '''

    # XXX: 并行安全性依赖于AchievementUnlock在数据库中的唯一性约束unique_together
    #     如果该约束被破坏，本函数将不再是原子化的，但不易发现
    _, created = AchievementUnlock.objects.get_or_create(
        user=user,
        achievement=achievement
    )

    # 是否成功解锁
    if created:
        # 如果有奖励元气值
        if achievement.reward_points > 0:
            User.objects.modify_YQPoint(
                user,
                achievement.reward_points,
                source=achievement.name,
                source_type=YQPointRecord.SourceType.ACHIEVE
            )
        # 发送通知 
        # TODO: sender 需要调整为 元培学院 官方账号
        # sender = Organization.objects.get(
        #     oname=CONFIG.yqpoint.org_name).get_user()
        content = f'恭喜您解锁新成就：{achievement.name}！'
        if achievement.reward_points > 0:
            content += f'获得{achievement.reward_points}元气值奖励！'
        notification_create(
            receiver=user,
            sender=user,  # 先用user代替
            typename=Notification.Type.NEEDREAD,
            title=Notification.Title.ACHIEVE_INFORM,
            content=content
        )

    return created


@return_on_except(False, Exception)
def bulk_add_achievement_record(user_list: QuerySet[User], achievement: Achievement):
    '''
    批量添加成就解锁记录
    若已解锁则不添加
    按需发布通知与发放元气值奖励

    Args:
    - user_list (QuerySet[User]): 待更改User的QuerySet
    - achievement (Achievement): 需添加的成就

    Returns:
    - bool: 是否成功添加

    Warning:
        本函数不保证原子性，仅保证并行安全性，但该实现存在风险
    '''

    # XXX: 并行安全性依赖于AchievementUnlock在数据库中的唯一性约束unique_together
    #     如果该约束被破坏，本函数将**重复解锁**成就。
    users_with_achievement = AchievementUnlock.objects.filter(
        achievement=achievement).values_list('user', flat=True)

    # 排除已经解锁的用户
    users_to_add = user_list.exclude(pk__in=users_with_achievement)
    # 批量添加成就解锁记录
    AchievementUnlock.objects.bulk_create([
        AchievementUnlock(user=user, achievement=achievement)
        for user in users_to_add
    ])

    # 批量添加元气值奖励
    User.objects.bulk_increase_YQPoint(
        users_to_add,
        achievement.reward_points,
        source=achievement.name,
        source_type=YQPointRecord.SourceType.ACHIEVE
    )

    # 批量发送通知
    # TODO: sender 需要调整为 元培学院 官方账号
    # sender = Organization.objects.get(oname=CONFIG.yqpoint.org_name).get_user()
    content = f'恭喜您解锁新成就：{achievement.name}！'
    if achievement.reward_points > 0:
        content += f'获得{achievement.reward_points}元气值奖励！'
    bulk_notification_create(
        receiver_list=users_to_add,
        sender=users_to_add[0],  # 先进行代替
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACHIEVE_INFORM,
        content=content
    )

    return True
