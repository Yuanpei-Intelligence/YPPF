from django.db import models
from django_mysql.models import ListCharField
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

import datetime
from boottest import local_dict


class NaturalPersonManager(models.Manager):
    def activated(self):
        return self.exclude(pstatus=NaturalPerson.status.GRADUATED)

    def autoset_status_annually(self):  # 修改毕业状态，每年调用一次
        datas = NaturalPerson.objects.activated()
        year = datetime.datetime.now().strftime('%Y')
        datas.objects.filter(pyear=str(int(year) - 4)).update(pstatus=1)

    def set_status(self, **kwargs):  # 延毕情况后续实现
        pass


class NaturalPerson(models.Model):
    # user = models.ForeignKey(User, to_field='username', on_delete=models.CASCADE)
    # pid = models.CharField(max_length=10, unique=True, primary_key=True)

    # Natural Person Attributes
    # pid = models.ForeignKey(User, to_field='username',
    #                        on_delete=models.CASCADE, unique=True, primary_key=True)
    pid = models.OneToOneField(to=User, on_delete=models.CASCADE)
    pname = models.CharField("姓名", max_length=10)
    pnickname = models.CharField("昵称", max_length=20, null=True, blank=True)  # 添加昵称

    class Gender(models.IntegerChoices):
        MALE = (0, "男")
        FEMALE = (1, "女")
        OTHER = (2, "其它")

    # pgender = models.CharField(max_length=10, null=True)
    pgender = models.SmallIntegerField('性别', choices=Gender.choices, null=True, blank=True)

    pemail = models.EmailField("邮箱", null=True, blank=True)
    ptel = models.CharField("电话", max_length=20, null=True, blank=True)
    pBio = models.TextField("自我介绍", max_length=1024, default='还没有填写哦～')
    avatar = models.ImageField(upload_to=f'avatar/', blank=True)
    firstTimeLogin = models.BooleanField(default=True)
    objects = NaturalPersonManager()
    QRcode = models.ImageField(upload_to=f'QRcode/', blank=True)

    YQPoint = models.FloatField("元气值", default=0.0)

    # Students Attributes
    pclass = models.CharField("班级", max_length=5, null=True, blank=True)
    pmajor = models.CharField("专业", max_length=25, null=True, blank=True)
    pyear = models.CharField("年级", max_length=5, null=True, blank=True)
    pdorm = models.CharField("宿舍", max_length=6, null=True, blank=True)  # 宿舍

    class status(models.IntegerChoices):
        UNDERGRADUATED = 0  # 未毕业
        GRADUATED = 1  # 毕业则注销

    pstatus = models.SmallIntegerField(
        '在校状态', choices=status.choices, default=0)  # 账户状态

    class Identity(models.IntegerChoices):
        TEACHER = 0
        STUDENT = 1

    TypeID = models.SmallIntegerField(
        '身份', choices=Identity.choices, default=1)  # 标识学生还是老师

    # 表示信息是否选择展示
    # '昵称','性别','邮箱','电话','专业','宿舍'
    show_nickname = models.BooleanField(default=True)
    show_gender = models.BooleanField(default=True)
    show_email = models.BooleanField(default=False)
    show_tel = models.BooleanField(default=False)
    show_major = models.BooleanField(default=True)
    show_dorm = models.BooleanField(default=False)

    def __str__(self):
        return str(self.pname)


class OrganizationType(models.Model):
    '''
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

    '''

    otype_id = models.SmallIntegerField(
        '组织类型编号', unique=True, primary_key=True)
    otype_name = models.CharField('组织类型名称', max_length=25)
    otype_superior_id = models.SmallIntegerField('上级组织类型编号', default=0)
    oincharge = models.ForeignKey(NaturalPerson, related_name='oincharge', on_delete=models.SET_NULL, blank=True,
                                  null=True)  # 相关组织的负责人
    ojob_name_list = ListCharField(
        base_field=models.CharField(max_length=10),
        size=4,
        max_length=44
    )

    def __str__(self):
        return str(self.otype_name)


class Semester(models.TextChoices):
    Fall = "Fall"
    Spring = "Spring"
    Annual = "Fall+Spring"


class OrganizationManager(models.Manager):
    def activated(self):
        return self.exclude(ostatus=False)


class Organization(models.Model):
    oid = models.OneToOneField(to=User, on_delete=models.CASCADE)
    # oid = models.ForeignKey(User, to_field='username',
    #                        on_delete=models.CASCADE, unique=True, primary_key=True)
    oname = models.CharField(max_length=32, unique=True)
    # 本质上的逻辑应该不是建立时间，而是现在这个组织处于哪一个周期
    # oestablished_time = models.DateField('建立时间')
    # oschool_year = models.IntegerField(
    #    "当前学年", default=int(datetime.datetime.now().strftime('%Y')))

    # oschool_semester = models.CharField(
    #    "当前学期", choices=Semester.choices,max_length=15)

    ostatus = models.BooleanField("激活状态", default=False)  # 表示一个组织是否上线(或者是已经被下线)

    objects = OrganizationManager()

    YQPoint = models.FloatField("元气值", default=0.0)
    ointroduction = models.TextField('介绍', null=True, blank=True, default="这里暂时没有介绍哦~")
    otype = models.ForeignKey(
        OrganizationType, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to=f'avatar/', blank=True)
    QRcode = models.ImageField(upload_to=f'QRcode/', blank=True)  # 二维码字段

    firstTimeLogin = models.BooleanField(default=True)  # 是否第一次登录

    def __str__(self):
        return str(self.oname)


class PositionManager(models.Manager):
    def activated(self):
        # 选择学年相同，并且学期相同或者覆盖的
        return self.filter(in_year=int(local_dict['semester_data']['year'])).filter(
            in_semester__contains=local_dict['semester_data']['semester'])


class Position(models.Model):
    """
    主席、部长、党支书
    副主席、副部长
    顾问
    部员、干事
    老师、助教、学生（课程）
    """
    person = models.ForeignKey(
        NaturalPerson, related_name='person', to_field="pid", on_delete=models.CASCADE,
    )
    org = models.ForeignKey(
        Organization, related_name='org',
        on_delete=models.CASCADE)

    # 职务的逻辑应该是0最高，1次之这样，然后数字映射到名字是在组织类型表中体现的
    # pos = models.CharField(verbose_name='职务', max_length=32, default='无')
    pos = models.IntegerField(verbose_name='职务等级', default=0)

    # 表示是这个组织哪一年、哪个学期的成员
    in_year = models.IntegerField(
        "当前学年", default=int(datetime.datetime.now().strftime('%Y')))
    in_semester = models.CharField(
        "当前学期", choices=Semester.choices, default=Semester.Annual, max_length=15)

    objects = PositionManager()
    # in_time = models.DateField('加入时间')
    # out_time = models.DateField('离开时间')


class Course(models.Model):
    cid = models.OneToOneField(to=Organization, on_delete=models.CASCADE, related_name="cid")
    # cid = models.ForeignKey(Organization, to_field="oid",
    #                        related_name='cid', on_delete=models.CASCADE, primary_key=True)
    # 不应该有这个字段了,这个字段应该自然的就是“组织的名字”
    # cname = models.CharField("课程名称", max_length=25)
    # season = models.CharField("开课时间", max_length=25)
    scheduler = models.CharField("上课时间", max_length=25)
    classroom = models.CharField("上课地点", max_length=25)
    evaluation_manner = models.CharField("考核方式", max_length=225)
    education_plan = models.CharField("教学计划", max_length=225)

    def __str__(self):
        return str(self.cid)


class Activity(models.Model):
    aname = models.CharField("活动名称", max_length=25)
    oid = models.ForeignKey(Organization, to_field="oid",
                            related_name='actoid', on_delete=models.CASCADE)
    ayear = models.IntegerField(
        "活动年份", default=int(datetime.datetime.now().strftime('%Y')))
    asemester = models.CharField(
        "活动学期", choices=Semester.choices, max_length=15)
    astart = models.DateTimeField("开始时间")  # 报名开始时间，
    afinish = models.DateTimeField("结束时间")  # 报名截止时间
    acontent = models.CharField("活动内容", max_length=1000)
    aURL = models.URLField("相关网址", null=True, blank=True)

    class Astatus(models.TextChoices):
        Asta_Pending = "审核中"
        Applying = "报名中"
        Waiting = "等待中"
        Processing = "进行中"
        Canceled = "已取消"
        Finish = "已结束"
        Unsucceed = "未通过"

    astatus = models.CharField("活动状态", choices=Astatus.choices, max_length=32, default=Astatus.Asta_Pending)
    mutableYQ = models.BooleanField("是否可以调整价格", default=False)
    max_people = models.IntegerField("活动最大人数", default=100)
    store_YQP = models.FloatField("已募集的元气值", default=0.0)  # 记录收到的元气值的多少
    YQPoint = ListCharField(
        base_field=models.IntegerField(default=0),
        size=10,
        max_length=50,
        default=[0]
    )  # 注意都×10了，使用时注意
    Places = ListCharField(
        base_field=models.CharField("活动地点", max_length=100),
        size=10,
        max_length=1100,
        default=["暂定"]
    )

    QRcode = models.ImageField(upload_to=f'QRcode/', blank=True)  # 二维码字段

    # 备记：活动二维码
    def __str__(self):
        return f"活动：{self.aname}"


# modified by Kinnuch & genuine
class TransferRecord(models.Model):
    proposer = models.ForeignKey(User, related_name='proposer_id', on_delete=models.CASCADE)
    recipient = models.ForeignKey(User, related_name='recipient_id', on_delete=models.CASCADE)
    amount = models.FloatField('转账元气值数量', default=0)
    time = models.DateTimeField('转账时间', auto_now_add=True)
    message = models.CharField("备注信息", max_length=255, default='')

    class Tstatus(models.IntegerChoices):
        ACCEPTED = 0  # 已接受
        WAITING = 1  # 等待确认中
        REFUSED = 2  # 已拒绝
        SUSPENDED = 3  # 已终止

    tstatus = models.IntegerField(choices=Tstatus.choices, default=1)

    class Meta:
        verbose_name = '转账信息'
        verbose_name_plural = verbose_name

        ordering = ['time']


class Paticipant(models.Model):
    aid = models.ForeignKey(Activity,
                            on_delete=models.CASCADE)
    pid = models.ForeignKey(

        NaturalPerson, on_delete=models.CASCADE)
