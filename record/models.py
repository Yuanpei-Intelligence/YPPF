from datetime import datetime

from django.db import models

from utils.models.choice import choice
from generic.models import User


__all__ = [
    'PageLog',
    'ModuleLog',
]


class PageLog(models.Model):
    '''
    统计Page类埋点数据(PV/PD)
    '''
    class Meta:
        verbose_name = "埋点记录-页面"
        verbose_name_plural = verbose_name

    class CountType(models.IntegerChoices):
        PV = choice(0, "Page View")
        PD = choice(1, "Page Disappear")

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.IntegerField('事件类型', choices=CountType.choices)

    page = models.URLField('页面url', max_length=256, blank=True)
    time = models.DateTimeField('发生时间', default=datetime.now)
    platform = models.CharField('设备类型', max_length=32, null=True, blank=True)
    explore_name = models.CharField('浏览器类型', max_length=32, null=True, blank=True)
    explore_version = models.CharField('浏览器版本', max_length=32, null=True, blank=True)


class ModuleLog(models.Model):
    '''
    统计Module类埋点数据(MV/MC)
    '''
    class Meta:
        verbose_name = "埋点记录-模块"
        verbose_name_plural = verbose_name

    class CountType(models.IntegerChoices):
        MV = choice(2, "Module View")
        MC = choice(3, "Module Click")

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.IntegerField('事件类型', choices=CountType.choices)

    page = models.URLField('页面url', max_length=256, blank=True)
    module_name = models.CharField('模块名称', max_length=64, blank=True)
    time = models.DateTimeField('发生时间', default=datetime.now)
    platform = models.CharField('设备类型', max_length=32, null=True, blank=True)
    explore_name = models.CharField('浏览器类型', max_length=32, null=True, blank=True)
    explore_version = models.CharField('浏览器版本', max_length=32, null=True, blank=True)
