from typing import Set
from django.db import models
from generic.models import User
from utils.models.descriptor import debug_only


# 宿舍类 只包含宿舍号
class Dormitory(models.Model):
    dorm_id = models.IntegerField("宿舍号")
    stu_number = models.IntegerField("当前人数", default=0)

    @debug_only
    def __str__(self):
        return str(self.dorm_id)
    
    
# 宿舍分配类 外键到宿舍和User
class DormitoryAssignment(models.Model):
    dormitory = models.ForeignKey(Dormitory, on_delete=models.CASCADE, verbose_name="宿舍号")
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="成员")
    time = models.DateTimeField("创建时间", auto_now_add=True)

    @debug_only
    def __str__(self):
        return str(self.dormitory.number) + " - " + self.user.username
    

    