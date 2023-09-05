from scheduler.periodic import periodical
from achievement.models import Achievement
from achievement.utils import bulk_add_achievement_record, get_students_by_grade


__all__ = [
    'unlock_credit_achievements',
    'new_school_year_achievements',
]


# 未扣除信用分
@periodical('cron', job_id='解锁信用分成就', day=1, hour=6, minute=0)
def unlock_credit_achievements():
    raise NotImplementedError


def new_school_year_achievements():
    '''触发 元气人生-开启大学第二、三、四年'''
    for i, name in zip(range(2, 7), ['二', '三', '四', '五', '六']):
        achievement = Achievement.objects.get(name=f'开启大学生活第{name}年')
        bulk_add_achievement_record(get_students_by_grade(i), achievement)
