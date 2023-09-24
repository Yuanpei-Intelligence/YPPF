from django.db import models

from utils.models.descriptor import admin_only
from generic.models import User

__all__ = ['AchievementType', 'Achievement', 'AchievementUnlock']


class AchievementType(models.Model):
    class Meta:
        verbose_name = '成就类型'
        verbose_name_plural = verbose_name

    title = models.CharField('名称', max_length=100)
    description = models.TextField('描述', blank=True)
    badge = models.ImageField('徽章', upload_to='achievement/badges/')
    avatar = models.ImageField('图标', upload_to='achievement/avatars/')

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
    class Meta:
        verbose_name = '成就'
        verbose_name_plural = verbose_name

    name = models.CharField('名称', max_length=100)
    description = models.TextField('描述')
    achievement_type = models.ForeignKey(
        AchievementType, on_delete=models.CASCADE, verbose_name='类型')
    hidden = models.BooleanField('隐藏', default=False)
    # Only used for filtering. Whether an achievement is auto-triggered is
    # not stored in the database.
    auto_trigger = models.BooleanField('自动触发', default=False)

    reward_points = models.PositiveIntegerField('奖励积分', default=0)

    @admin_only
    def __str__(self):
        return self.name


class AchievementUnlock(models.Model):
    class Meta:
        verbose_name = '成就解锁记录'
        verbose_name_plural = verbose_name
        # XXX: 工具函数的并行安全性完全依赖于此约束
        unique_together = ['user', 'achievement']

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE,
                                    verbose_name='解锁成就')
    time = models.DateTimeField('解锁时间', auto_now_add=True)
    private = models.BooleanField('不公开', default=False)
