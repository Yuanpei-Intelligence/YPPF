from django.db import models

from utils.models.descriptor import admin_only
from generic.models import User

__all__ = ['AchievementType', 'Achievement', 'AchievementUnlock']


class AchievementType(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    badge = models.ImageField(upload_to='achievement/images/badges')
    avatar = models.ImageField(upload_to='achievement/images/avatars')

    @admin_only
    def __str__(self):
        return self.title

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
    hidden = models.BooleanField(default=False)
    # Only used for filtering. Whether an achievement is auto-triggered is
    # not stored in the database.
    auto_trigger = models.BooleanField(default=False)

    reward_points = models.PositiveIntegerField(default=0)

    @admin_only
    def __str__(self):
        return self.name


class AchievementUnlock(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    time = models.DateTimeField("解锁时间", auto_now_add=True)
    private = models.BooleanField(default=False)

    class Meta:
        unique_together = ['user', 'achievement']
