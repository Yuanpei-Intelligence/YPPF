from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
# Create your models here.
class student(models.Model):
    sno = models.CharField(max_length=10, unique=True, primary_key=True)
    sname = models.CharField(max_length=10, null=True)
    username = models.ForeignKey(User, to_field='username', on_delete=models.CASCADE)
    sgender = models.CharField(max_length=10, null=True)
    syear = models.CharField(max_length=4, null=True)
    semail = models.CharField(max_length=100,null=True)
    sclass = models.CharField(max_length=5,null=True)
    smajor = models.CharField(max_length=25,null=True)
    stel = models.CharField(max_length=20,null=True)
    sBio = models.TextField(max_length=1024,default='还没有填写哦～')
    avatar = models.ImageField(upload_to=f'avatar/',blank=True)
    firstTimeLogin = models.BooleanField(default=True)
    def __str__(self):
        return "学生：" + str(self.syear) + '级 ' + str(self.sno) + ' ' + str(self.sname)

class organization(models.Model):
    organization_name = models.CharField(max_length=32,default='暂未加入学工组织')
    department = models.CharField(max_length=32,null=True,blank=True)
    def __str__(self):
        if self.department is not None:
            return self.organization_name + str(self.department)
        else:
            return self.organization_name

class position(models.Model):
    position_stu = models.ForeignKey(
        student, related_name='position_stu', on_delete=models.CASCADE,
    )
    from_organization = models.ForeignKey(
        organization, related_name='org_from',on_delete=models.CASCADE)#,default=organization.objects.get(organization_name='暂未加入学工组织'))

    job = models.CharField(verbose_name='职务',max_length=32,default='无')

    def __str__(self):
        return '机构：' + str(self.from_organization.organization_name) + '; 部门：' + str(self.from_organization.department)
        + "；负责人：" + str(self.position_stu.sname)

#@receiver(post_save,sender=student)
#def create_position(sender, instance, created, **kwargs):
#    if created:
#        position.objects.create(position_stu=instance)
        
# @receiver(post_save, sender=student)
# def save_position(sender, instance, **kwargs):
#     instance.s