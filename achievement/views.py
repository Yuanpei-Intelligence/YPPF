from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from app.models import NaturalPerson
from .models import AchievementUnlock, Achievement, AchievementType
from app.utils import (
    get_sidebar_and_navbar,
)
'''

@login_required
def view_achievements(request):
    user = request.user
    student = NaturalPerson.objects.get(person_id=user)
    invisible_achievements = AchievementUnlock.objects.filter(
        user=user, private=True)
    visible_achievements = AchievementUnlock.objects.filter(
        user=user, private=False)
    
    unlocked_achievements = AchievementUnlock.objects.filter(user=user)
    achievement_types = AchievementType.objects.filter(pk__in=unlocked_achievements)
    
    for acs in achievement_types:
        print(acs.title, acs.badge)
    
    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(
        request.user, "成就展示")
    frontend_dict["warn_code"] = request.GET.get('warn_code', 0)
    frontend_dict["warn_message"] = request.GET.get('warn_message', "")
    bar_display = frontend_dict["bar_display"]

    return render(request, 'viewAchievements.html', locals())

@login_required
def view_achievementType(request, achievementTypeName: str):
    user = request.user
    student = NaturalPerson.objects.get(person_id=user)
    achievement_type = AchievementType.objects.get(title=achievementTypeName)
    
    achievement_all = Achievement.objects.filter(achievement_type=achievement_type)
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
    
    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(
        request.user, "成就大类")
    frontend_dict["warn_code"] = request.GET.get('warn_code', 0)
    frontend_dict["warn_message"] = request.GET.get('warn_message', "")
    bar_display = frontend_dict["bar_display"]

    return render(request, 'viewAchievementType.html', locals())
'''