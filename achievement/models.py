from typing import List, Dict, Set

from django.db import models
from django.db import models
from django.http import HttpRequest

from generic.models import User
from app.utils_dependency import *
from app.models import NaturalPerson

__all__ = ['AchievementType', 'Achievement', 'AchievementUnlock']


class AchievementType(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    badge = models.ImageField(upload_to='achievement/images/badges')
    avatar = models.ImageField(upload_to='achievement/images/avatars')

    # Actual types in use (remove later)
    # UNDEFINED = (0, "未定义")
    # YUANQIRENSHENG = (1, "元气人生")
    # JIESHENZIHAO = (2, "洁身自好")
    # WUYUBINGJU = (3, "五育并举")
    # ZHITONGDAOHE = (4, "志同道合")
    # YANYULVJI = (5, "严于律己")
    # YUANQIMANMAN = (6, "元气满满")
    # SANWUCHENGQUN = (7, "三五成群")
    # ZHIHUISHWNGHUO = (8, "智慧生活")


class Achievement(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    achievement_type = models.ForeignKey(
        AchievementType, on_delete=models.CASCADE)
    # while is_hidden is True, the achievement's trigger is not visiable to user
    is_hidden = models.BooleanField(default=False)
    # while is_auto_trigger is True, the system will automatically check trigger conditions
    auto_trigger = models.BooleanField(default=False)

    reward_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name


class AchievementUnlock(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    time = models.DateTimeField("解锁时间", auto_now_add=True)
    private = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} unlocked {self.achievement.name}"
