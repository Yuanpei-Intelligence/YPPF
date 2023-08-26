"""
初始化 AchievementType Achievement
"""
from achievement.models import AchievementType, Achievement
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "init AchievementType Achievement"

    def handle(self, *args, **options):
        pass
