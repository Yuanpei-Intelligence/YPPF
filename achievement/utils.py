from django.db import transaction
from django.db.models import QuerySet

from generic.models import User, YQPointRecord
from app.models import NaturalPerson
from app.models import Notification
from utils.wrap import return_on_except
from app.notification_utils import notification_create, bulk_notification_create
from semester.api import current_semester
from utils.marker import need_refactor

from .models import Achievement, AchievementType, AchievementUnlock

__all__ = ['stuinfo_set_achievement'
           'trigger_achievement',
            'bulk_add_achievement_record',
            'get_students_by_grade',]

'''成就系统 API
- 处理用户触发成就
- 后台批量添加成就
'''

def stuinfo_set_achievement(user):
    student = NaturalPerson.objects.get(person_id=user)
    invisible_achievements = AchievementUnlock.objects.filter(
            user=user, private=True)
    visible_achievements = AchievementUnlock.objects.filter(
            user=user, private=False)

    unlocked_achievements = AchievementUnlock.objects.filter(user=user)
    achievement_types = AchievementType.objects.all().order_by('id')
    display_tuple = []  # (achievement_type, unlocked num, all num, achievement_unlocked, achievement_locked, achievement_locked_hidden)
    for a_t in achievement_types:
        all_achievement_stat = Achievement.objects.filter(
                achievement_type=a_t).count()
        achievement_a_t = Achievement.objects.filter(achievement_type=a_t)
        unlocked_personal_stat = unlocked_achievements.filter(
                achievement__in=achievement_a_t).count()
        
        achievement_all = Achievement.objects.filter(achievement_type=a_t)
        achievement_all_num = achievement_all.count()
    
        achievement_unlocked = []
        # achievement_unlocked is the list of unlocked achievements which are not hidden
        achievement_locked = []
        achievement_locked_hidden = []
        for achievement in achievement_all:
                # count achievementUnlocks attached to achievement
                if AchievementUnlock.objects.filter(achievement=achievement, user=user).count():
                        achievement_unlocked.append(achievement)
                else:
                        if achievement.hidden:
                                achievement_locked_hidden.append(achievement)
                        else:
                                achievement_locked.append(achievement)
        achievement_num = len(achievement_unlocked)
        
        display_tuple.append((a_t, unlocked_personal_stat, all_achievement_stat, achievement_unlocked, achievement_locked, achievement_locked_hidden))
        # print("unlocked_personal_stat", unlocked_personal_stat)
        # print("all_achievement_stat", all_achievement_stat)
        
        # works, but ugly, need to be improved in the future
    achievement_types_0 = display_tuple[:3]
    achievement_types_1 = display_tuple[3:6]
    achievement_types_2 = display_tuple[6:9]
    return invisible_achievements, visible_achievements, achievement_types_0, achievement_types_1, achievement_types_2


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
