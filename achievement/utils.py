'''成就系统 API
- 处理用户触发成就
- 后台批量添加成就
'''
from datetime import date

from django.db import transaction
from django.db.models import QuerySet

from generic.models import User, YQPointRecord, CreditRecord
from app.models import Notification
from achievement.models import Achievement, AchievementType, AchievementUnlock
from utils.wrap import return_on_except
from app.notification_utils import notification_create, bulk_notification_create
from semester.api import current_semester
from utils.marker import need_refactor


__all__ = [
    'personal_achievements',
    'trigger_achievement',
    'bulk_add_achievement_record',
    'get_students_by_grade',
    'get_students_without_credit_record',
]


def personal_achievements(user: User):
    unlocked_achievements = AchievementUnlock.objects.filter(user=user)
    invisible_achievements = list(unlocked_achievements.filter(private=True))
    visible_achievements = list(unlocked_achievements.filter(private=False))

    unlocked_ids = list(unlocked_achievements.values_list('achievement', flat=True))
    achievement_types = AchievementType.objects.all().order_by('id')
    # （类型，总数，已解锁成就，未解锁成就，隐藏成就）
    display_by_types = []
    for achievement_type in achievement_types:
        achievements = Achievement.objects.filter(achievement_type=achievement_type)
        unlocked = list(achievements.filter(pk__in=unlocked_ids))
        all_locked = achievements.exclude(pk__in=unlocked_ids)
        locked = list(all_locked.filter(hidden=False))
        hidden = list(all_locked.filter(hidden=True))
        display_by_types.append((
            achievement_type,
            achievements.count(),
            unlocked,
            locked,
            hidden,
        ))
    return invisible_achievements, visible_achievements, display_by_types


@return_on_except(False, Exception)
@transaction.atomic
def trigger_achievement(user: User, achievement: Achievement):
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
        本函数保证原子化，且保证并行安全性，但后者实现存在风险
    '''

    # XXX: 并行安全性依赖于AchievementUnlock在数据库中的唯一性约束unique_together
    #     如果该约束被破坏，本函数将不再是安全的，但不易发现
    _, created = AchievementUnlock.objects.get_or_create(
        user=user,
        achievement=achievement
    )

    # 是否成功解锁
    assert created, '成就已解锁'

    content = f'恭喜您解锁新成就：{achievement.name}！'
    # 如果有奖励元气值
    if achievement.reward_points > 0:
        User.objects.modify_YQPoint(
            user,
            achievement.reward_points,
            source=achievement.name,
            source_type=YQPointRecord.SourceType.ACHIEVE
        )
        content += f'获得{achievement.reward_points}元气值奖励！'
    notification_create(
        receiver=user,
        sender=None,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACHIEVE_INFORM,
        content=content
    )

    return True


@return_on_except(False, Exception)
@transaction.atomic
def bulk_add_achievement_record(users: QuerySet[User], achievement: Achievement):
    '''
    批量添加成就解锁记录
    若已解锁则不添加
    按需发布通知与发放元气值奖励

    Args:
    - users (QuerySet[User]): 待更改User的QuerySet
    - achievement (Achievement): 需添加的成就

    Returns:
    - bool: 是否成功添加

    Warning:
        本函数保证原子化，且保证并行安全性，但后者实现存在风险
    '''

    # XXX: 并行安全性依赖于AchievementUnlock在数据库中的唯一性约束unique_together
    #     如果该约束被破坏，本函数将**重复解锁**成就。
    users_with_achievement = AchievementUnlock.objects.filter(
        achievement=achievement).values_list('user', flat=True)

    # 排除已经解锁的用户
    users_to_add = users.exclude(pk__in=users_with_achievement)
    # 批量添加成就解锁记录
    AchievementUnlock.objects.bulk_create([
        AchievementUnlock(user=user, achievement=achievement)
        for user in users_to_add
    ])

    content = f'恭喜您解锁新成就：{achievement.name}！'

    if achievement.reward_points > 0:
        User.objects.bulk_increase_YQPoint(
            users_to_add,
            achievement.reward_points,
            source=achievement.name,
            source_type=YQPointRecord.SourceType.ACHIEVE
        )
        content += f'获得{achievement.reward_points}元气值奖励！'
    bulk_notification_create(
        users_to_add,
        sender=None,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.ACHIEVE_INFORM,
        content=content
    )

    return True


@need_refactor
def get_students_by_grade(grade: int) -> QuerySet[User]:
    '''
    传入目标入学年份数，返回满足的、未毕业的学生User列表。
    示例：今年是2023年，我希望返回入学第二年的user，即查找username前两位为22的user
    仅限秋季学期开始后使用。
    '''
    semester_year = current_semester().year
    goal_year = semester_year - 2000 - grade + 1
    students = User.objects.filter_type(User.Type.STUDENT).filter(
        active=True, username__startswith=str(goal_year))
    return students


def get_students_without_credit_record(start_date: date, end_date: date) -> QuerySet[User]:
    '''
    获取一段时间内没有扣分记录的在读同学

    Args:
    - start_date: 查询起始时间
    - end_date: 查询结束时间

    Returns:
    - QuerySet[User]: 没有扣分记录的在读同学
    '''
    records = CreditRecord.objects.filter(
        time__date__gte=start_date, time__date__lte=end_date)
    students = User.objects.filter_type(User.Type.STUDENT).filter(
        active=True).exclude(pk__in=records.values_list('user', flat=True))
    return students
