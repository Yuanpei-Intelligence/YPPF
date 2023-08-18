from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from app.models import NaturalPerson
from .models import AchievementUnlock, Achievement, AchievementType
from app.utils import (
    get_sidebar_and_navbar,
)

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
