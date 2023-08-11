from django.db import models

from utils.models.descriptor import debug_only
from generic.models import User


class Dormitory(models.Model):
    id = models.BigAutoField('宿舍号', primary_key=True)
    capacity = models.IntegerField('容量', default=4)
    gender = models.CharField(
        '性别', max_length=1, choices=(('M', '男'), ('F', '女')))

    @debug_only
    def __str__(self):
        return str(self.id)


class DormitoryAssignment(models.Model):
    dormitory = models.ForeignKey(
        Dormitory, on_delete=models.CASCADE, verbose_name='宿舍号')
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='成员')
    time = models.DateTimeField('创建时间', auto_now_add=True)
    bed_id = models.IntegerField('床位号')

    @debug_only
    def __str__(self):
        return str(self.dormitory.number) + ' - ' + self.user.username
