from django.shortcuts import render
from .models import Achievement, AchievementUnlock
from django.contrib.auth.decorators import login_required

from app.models import NaturalPerson


@login_required
def view_achievements(request):
    user = request.user
    student = NaturalPerson.objects.get(person_id=user)
    unlocked_achievements = AchievementUnlock.objects.filter(user=user)
    hidden_achievements = AchievementUnlock.objects.filter(
        student=student, is_hidden=True)
    visible_achievements = AchievementUnlock.objects.filter(
        student=student, is_hidden=False)

    return render(request, 'achievement/view_achievements.html', {
        'student': student,
        'unlocked_achievements': unlocked_achievements,
        'hidden_achievements': hidden_achievements,
        'visible_achievements': visible_achievements,
    })
