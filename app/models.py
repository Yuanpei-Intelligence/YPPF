from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

import datetime


class NaturalPersonManager(models.Manager):
    def activated(self):
        return self.exclude(sstatus=NaturalPerson.status.GRADUATED)

    def autoset_status_annually(self):  # 修改毕业状态，每年调用一次
        datas = NaturalPerson.pmanager.activated()
        year = datetime.datetime.now().strftime('%Y')
        datas.objects.filter(pyear=str(int(year) - 4)).update(sstatus=1)

    def set_status(self, **kwargs):  # 延毕情况后续实现
        pass


class NaturalPerson(models.Model):
    # user = models.ForeignKey(User, to_field='username', on_delete=models.CASCADE)
    # pid = models.CharField(max_length=10, unique=True, primary_key=True)

    # Natural Person Attributes
    pid = models.ForeignKey(User, to_field='username', on_delete=models.CASCADE,unique=True)
    pname = models.CharField(max_length=10, null=True)
    pgender = models.CharField(max_length=10, null=True)

    pemail = models.CharField(max_length=100, null=True)
    ptel = models.CharField(max_length=20, null=True)
    pBio = models.TextField(max_length=1024, default='还没有填写哦～')
    avatar = models.ImageField(upload_to=f'avatar/', blank=True)
    firstTimeLogin = models.BooleanField(default=True)
    pmanager = NaturalPersonManager()

    pyqp = models.IntegerField("元气值")

    # Students Attributes
    sclass = models.CharField(max_length=5, null=True)
    smajor = models.CharField(max_length=25, null=True)
    syear = models.CharField(max_length=5, null=True)
    sdorm = models.CharField(max_length=6, null=True)  # 宿舍

    class status(models.IntegerChoices):
        UNDERGRADUATED = 0  # 未毕业
        GRADUATED = 1  # 毕业则注销

    sstatus = models.SmallIntegerField('在校状态', choices=status.choices, default=0)  # 账户状态

    class Identity(models.IntegerChoices):
        TEACHER = 0
        STUDENT = 1

    TypeID = models.SmallIntegerField('身份', choices=Identity.choices, default=1)  # 标识学生还是老师

    def __str__(self):
        return "学生：" + str(self.pyear) + '级 ' + str(self.pid) + ' ' + str(self.pname)


class OrganizationType(models.Model):
    class OType(models.IntegerChoices):
        NONE = -1
        YUANPEI_XUEYUAN = 0

        YUANPEI_DANGWEI = 1

        YUANPEI_TUANWEI = 100
        TUANWEI_BUMEN = 101

        YUANPEI_XUESHENGHUI = 200
        XUESHENGHUI_ZHUXITUAN = 210
        XUESHENGHUI_BUMEN = 220

        YUANPEI_XUEXUEXUE = 300
        XUEXUEXUE_ZHUXITUAN = 310
        XUEXUEXUE_BUMEN = 320
        XUEXUEXUE_XUEHUI = 330

        HESHANHENG_TUSHUSHI = 400

        YUANPEI_SHEJIZU = 500

        DIXIADIANYINGYUAN = 600

        BIANLUNDUI = 700

        SHUYUAN_KECHENG = 800

    otype_id = models.SmallIntegerField('组织类型编号', default=-1,unique=True)
    otype_name = models.CharField('组织类型名称',max_length=25)
    otype_superior_id = models.SmallIntegerField('上级组织类型编号', default=0)


class Organization(models.Model):
    oid = models.ForeignKey(User, to_field='username', on_delete=models.CASCADE,unique=True)
    oname = models.CharField(max_length=32, default='暂未加入学工组织')
    oestablished_time = models.DateField('建立时间')
    oyqp = models.IntegerField('元气值',default=0)
    ostatus = models.CharField('状态（备用字段）',max_length=25)
    otype_id = models.ForeignKey(OrganizationType, to_field="otype_id", on_delete=models.CASCADE)

    def __str__(self):
        return self.oname


class Position(models.Model):
    """
    主席、部长、党支书
    副主席、副部长
    顾问
    部员、干事
    老师、助教、学生（课程）
    """
    person = models.ForeignKey(
        NaturalPerson, related_name='person', to_field="pid",on_delete=models.CASCADE,
    )
    org = models.ForeignKey(
        Organization, related_name='org',
        on_delete=models.CASCADE)
    pos = models.CharField(verbose_name='职务', max_length=32, default='无')
    in_time = models.DateField('加入时间')
    out_time = models.DateField('离开时间')



class Course(models.Model):
    cid = models.ForeignKey(Organization, to_field="oid",related_name='cid', on_delete=models.CASCADE)
    cname = models.CharField("课程名称",max_length=25)
    season = models.CharField("开课时间",max_length=25)
    scheduler = models.CharField("上课时间",max_length=25)
    classroom = models.CharField("上课地点",max_length=25)
    evaluation_manner = models.CharField("考核方式",max_length=225)
    education_plan = models.CharField("教学计划",max_length=225)

    def __str__(self):
        return f"课程：{self.cname}"

class Activation(models.Model):
    aid = models.IntegerField("活动编号",unique=True)
    aname = models.CharField("活动名称",max_length=25)
    oid = models.ForeignKey(Organization, to_field="oid",related_name='actoid', on_delete=models.CASCADE,unique=True)
    acontent = models.CharField("活动内容",max_length=225)

    def __str__(self):
        return f"活动：{self.aname}"

class Paticipant(models.Model):
    aid = models.ForeignKey(Activation, to_field="aid", on_delete=models.CASCADE)
    pid = models.ForeignKey(NaturalPerson, to_field="pid", on_delete=models.CASCADE)
