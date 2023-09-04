from generic.models import User

from app.models import NaturalPerson

from .models import Achievement, AchievementType, AchievementUnlock

__all__ = ['stuinfo_set_achievement']

def stuinfo_set_achievement(user):
    student = NaturalPerson.objects.get(person_id=user)
    invisible_achievements = AchievementUnlock.objects.filter(
            user=user, private=True)
    visible_achievements = AchievementUnlock.objects.filter(
            user=user, private=False)

    unlocked_achievements = AchievementUnlock.objects.filter(user=user)
    achievement_types = AchievementType.objects.all().order_by('id')
    display_tuple = []  # (achievement_type, unlocked num, all num)
    for a_t in achievement_types:
        all_achievement_stat = Achievement.objects.filter(
                achievement_type=a_t).count()
        achievement_a_t = Achievement.objects.filter(achievement_type=a_t)
        unlocked_personal_stat = unlocked_achievements.filter(
                achievement__in=achievement_a_t).count()
        display_tuple.append((a_t, unlocked_personal_stat, all_achievement_stat))
        # print("unlocked_personal_stat", unlocked_personal_stat)
        # print("all_achievement_stat", all_achievement_stat)
        
        # works, but ugly, need to be improved in the future
    achievement_types_0 = display_tuple[:3]
    achievement_types_1 = display_tuple[3:6]
    achievement_types_2 = display_tuple[6:9]
    return invisible_achievements, visible_achievements, achievement_types_0, achievement_types_1, achievement_types_2

