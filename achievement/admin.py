from django.contrib import admin

from .models import *


@admin.register(AchievementType)
class AchievementTypeAdmin(admin.ModelAdmin):
    list_display = ['title', 'description']
    search_fields = ['title']


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ['name', 'description',
                    'achievement_type', 'hidden', 'auto_trigger']
    search_fields = ['name']


@admin.register(AchievementUnlock)
class AchievementUnlockAdmin(admin.ModelAdmin):
    list_display = ['user', 'achievement',
                    'time', 'private']
    search_fields = ['user', 'achievement']
