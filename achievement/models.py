from django.db import models

from django.db import models
from django.contrib.auth.models import User

from typing import List, Dict, Set

from django.http import HttpRequest

from app.utils_dependency import *
from app.models import NaturalPerson

from app.config import UTYPE_PER
class AchievementType(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    badge = models.ImageField(upload_to='achievement/images/')
    
    class Series(models.IntegerChoices):
        # change them if there are any better translations!
        UNDEFINED = (0, "未定义")
        YUANQIRENSHENG = (1, "元气人生")
        JIESHENZIHAO = (2, "洁身自好")
        WUYUBINGJU = (3, "五育并举")
        ZHITONGDAOHE = (4, "志同道合")
        YANYULVJI = (5, "严于律己")
        YUANQIMANMAN = (6, "元气满满")
        SANWUCHENGQUN = (7, "三五成群")
        ZHIHUISHWNGHUO = (8, "智慧生活")

class Achievement(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    achievement_type = models.ForeignKey(AchievementType, on_delete=models.CASCADE)
    
    class trigger_condition(models.IntegerChoices):
        UNDIFINED = (0, "未定义")
        AUTO = (1, "系统自动")
        QRCODE = (2, "二维码")
        COURSE = (3, "书院课程")
        DORM = (4, "楼宇管理")
    
    reward_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

class AchievementUnlock(models.Model):
    student = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE)
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    date_unlocked = models.DateField("解锁时间", auto_now_add=True)
    is_hidden = models.BooleanField(default=False)
    is_visible_to_others = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} unlocked {self.achievement.name}"

