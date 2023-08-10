from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from app.models import NaturalPerson
from .models import AchievementUnlock


@login_required
def view_achievements(request):
    user = request.user
    student = NaturalPerson.objects.get(person_id=user)
    invisible_achievements = AchievementUnlock.objects.filter(
        user=user, private=True)
    visible_achievements = AchievementUnlock.objects.filter(
        user=user, private=False)

    return render(request, 'achievement/view_achievements.html', {
        'student': student,
        'invisible_achievements': invisible_achievements,
        'visible_achievements': visible_achievements,
    })
