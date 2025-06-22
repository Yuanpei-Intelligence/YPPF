from django.db import models

from utils.models.descriptor import admin_only
from utils.models.choice import choice
from generic.models import User

__all__ = [
    'Dormitory',
    'DormitoryAssignment',
    'Agreement'
]

class Agreement(models.Model):

    class Meta:
        verbose_name = '住宿协议'
        verbose_name_plural = verbose_name

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户')
    sign_time = models.DateTimeField('签订时间', auto_now_add=True)


class Dormitory(models.Model):
    class Meta:
        verbose_name = '宿舍'
        verbose_name_plural = verbose_name

    id = models.BigAutoField('宿舍号', primary_key=True)
    capacity = models.IntegerField('容量', default=4)

    class Gender(models.TextChoices):
        MALE = choice('M', '男')
        FEMALE = choice('F', '女')

    gender = models.CharField('性别', max_length=1, choices=Gender.choices)

    def __str__(self):
        return str(self.id)


class DormitoryAssignment(models.Model):
    class Meta:
        verbose_name = '宿舍分配信息'
        verbose_name_plural = verbose_name

    dormitory = models.ForeignKey(
        Dormitory, on_delete=models.CASCADE, verbose_name='宿舍号')
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='成员')
    bed_id = models.IntegerField('床位号')
    time = models.DateTimeField('创建时间', auto_now_add=True)
