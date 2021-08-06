from django.db import models
from django.db.models.enums import Choices
from django_mysql.models import ListCharField
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from datetime import datetime, timedelta
from boottest import local_dict


class NaturalPersonManager(models.Manager):
    def activated(self):
        return self.exclude(status=NaturalPerson.GraduateStatus.GRADUATED)

    def autoset_status_annually(self):  # 修改毕业状态，每年调用一次
        datas = NaturalPerson.objects.activated()
        year = datetime.now().strftime("%Y")
        datas.objects.filter(stu_grade=str(int(year) - 4)
                             ).update(GraduateStatus=1)

    def set_status(self, **kwargs):  # 延毕情况后续实现
        pass


class NaturalPerson(models.Model):
    class Meta:
        verbose_name = "自然人"
        verbose_name_plural = verbose_name

    # Common Attributes
    person_id = models.OneToOneField(to=User, on_delete=models.CASCADE)
    name = models.CharField("姓名", max_length=10)
    nickname = models.CharField("昵称", max_length=20, null=True, blank=True)

    class Gender(models.IntegerChoices):
        MALE = (0, "男")
        FEMALE = (1, "女")

    gender = models.SmallIntegerField(
        "性别", choices=Gender.choices, null=True, blank=True
    )

    email = models.EmailField("邮箱", null=True, blank=True)
    telephone = models.CharField("电话", max_length=20, null=True, blank=True)
    biography = models.TextField("自我介绍", max_length=1024, default="还没有填写哦～")
    avatar = models.ImageField(upload_to=f"avatar/", blank=True)
    first_time_login = models.BooleanField(default=True)
    objects = NaturalPersonManager()
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)

    YQPoint = models.FloatField("元气值", default=0)

    class Identity(models.IntegerChoices):
        TEACHER = (0, "教职工")
        STUDENT = (1, "学生")

    identity = models.SmallIntegerField(
        "身份", choices=Identity.choices, default=1
    )  # 标识学生还是老师

    # Students Attributes
    stu_class = models.CharField("班级", max_length=5, null=True, blank=True)
    stu_major = models.CharField("专业", max_length=25, null=True, blank=True)
    stu_grade = models.CharField("年级", max_length=5, null=True, blank=True)
    stu_dorm = models.CharField("宿舍", max_length=6, null=True, blank=True)

    class GraduateStatus(models.IntegerChoices):
        UNDERGRADUATED = 0  # 未毕业
        GRADUATED = 1  # 毕业则注销

    status = models.SmallIntegerField(
        "在校状态", choices=GraduateStatus.choices, default=0)

    # 表示信息是否选择展示
    # '昵称','性别','邮箱','电话','专业','宿舍'
    show_nickname = models.BooleanField(default=True)
    show_gender = models.BooleanField(default=True)
    show_email = models.BooleanField(default=False)
    show_tel = models.BooleanField(default=False)
    show_major = models.BooleanField(default=True)
    show_dorm = models.BooleanField(default=False)

    # 注意：这是不订阅的列表！！
    subscribe_list = models.ManyToManyField(
        'Organization', related_name='unsubsribers', db_index=True)

    def __str__(self):
        return str(self.name)

    def show_info(self):
        """
            返回值为一个列表，在search.html中使用，按照如下顺序呈现：
            people_field = ['姓名', '年级', '班级', '专业', '状态']
            其中未公开的属性呈现为‘未公开’
            注意：major, gender, nickname, email, tel, dorm可能为None
            班级和年级现在好像也可以为None
        """
        unpublished = '未公开'
        gender = ['男', '女']
        info = [self.name, self.stu_grade, self.stu_class]
        #info.append(self.nickname if (self.show_nickname) else unpublished)
        #info.append(
        #    unpublished if ((not self.show_gender) or (self.gender == None)) else gender[self.gender])
        info.append(self.stu_major if (self.show_major) else unpublished)
        #info.append(self.email if (self.show_email) else unpublished)
        #info.append(self.telephone if (self.show_tel) else unpublished)
        #info.append(self.stu_dorm if (self.show_dorm) else unpublished)
        info.append('在校' if self.status ==
                    NaturalPerson.GraduateStatus.UNDERGRADUATED else '已毕业')
        # 防止显示None
        for i in range(len(info)):
            if info[i] == None:
                info[i] = unpublished
        return info

    def save(self, *args, **kwargs):
        self.YQPoint = round(self.YQPoint, 1)
        super(NaturalPerson, self).save(*args, **kwargs)


class OrganizationType(models.Model):
    class Meta:
        verbose_name = "组织类型"
        verbose_name_plural = verbose_name

    otype_id = models.SmallIntegerField(
        "组织类型编号", unique=True, primary_key=True)
    otype_name = models.CharField("组织类型名称", max_length=25)
    otype_superior_id = models.SmallIntegerField("上级组织类型编号", default=0)
    incharge = models.ForeignKey(
        NaturalPerson,
        related_name="incharge",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )  # 相关组织的负责人
    job_name_list = ListCharField(
        base_field=models.CharField(max_length=10), size=4, max_length=44
    )  # [部长, 副部长, 部员]

    def __str__(self):
        return str(self.otype_name)

    def get_name(self, pos):
        if pos >= len(self.job_name_list):
            return "成员"
        return self.job_name_list[pos]


class Semester(models.TextChoices):
    FALL = "Fall"
    SPRING = "Spring"
    ANNUAL = "Fall+Spring"

    def get(semester):  # read a string indicating the semester, return the correspoding status
        if semester == "Fall":
            return Semester.FALL
        elif semester == "Spring":
            return Semester.SPRING
        elif semester == "Annual":
            return Semester.ANNUAL
        else:
            raise NotImplementedError("出现未设计的学期状态")

class OrganizationManager(models.Manager):
    def activated(self):
        return self.exclude(status=False)


class Organization(models.Model):
    class Meta:
        verbose_name = "组织"
        verbose_name_plural = verbose_name

    organization_id = models.OneToOneField(to=User, on_delete=models.CASCADE)
    oname = models.CharField(max_length=32, unique=True)
    otype = models.ForeignKey(OrganizationType, on_delete=models.CASCADE)
    status = models.BooleanField("激活状态", default=True)  # 表示一个组织是否上线(或者是已经被下线)

    objects = OrganizationManager()

    YQPoint = models.FloatField("元气值", default=0.0)
    introduction = models.TextField(
        "介绍", null=True, blank=True, default="这里暂时没有介绍哦~")
    avatar = models.ImageField(upload_to=f"avatar/", blank=True)
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)  # 二维码字段

    first_time_login = models.BooleanField(default=True)  # 是否第一次登录

    def __str__(self):
        return str(self.oname)

    def save(self, *args, **kwargs):
        self.YQPoint = round(self.YQPoint, 1)
        super(Organization, self).save(*args, **kwargs)


class PositionManager(models.Manager):
    def activated(self):
        # 选择学年相同，并且学期相同或者覆盖的
        return self.filter(in_year=int(local_dict["semester_data"]["year"])).filter(
            in_semester__contains=local_dict["semester_data"]["semester"]
        )


class Position(models.Model):
    """
    主席、部长、党支书
    副主席、副部长
    顾问
    部员、干事
    老师、助教、学生（课程）
    """

    class Meta:
        verbose_name = "职务"
        verbose_name_plural = verbose_name

    person = models.ForeignKey(
        NaturalPerson,
        to_field="person_id",
        on_delete=models.CASCADE,
    )
    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE)

    # 职务的逻辑应该是0最高，1次之这样，然后数字映射到名字是在组织类型表中体现的
    pos = models.IntegerField(verbose_name="职务等级", default=0)

    # 是否选择公开当前的职务
    show_post = models.BooleanField(default=True)

    # 表示是这个组织哪一年、哪个学期的成员
    in_year = models.IntegerField(
        "当前学年", default=int(datetime.now().strftime("%Y")))
    in_semester = models.CharField(
        "当前学期", choices=Semester.choices, default=Semester.ANNUAL, max_length=15
    )

    objects = PositionManager()


class Course(models.Model):
    class Meta:
        verbose_name = "课程"
        verbose_name_plural = verbose_name

    cid = models.OneToOneField(
        to=Organization, on_delete=models.CASCADE, 
    )
    # 课程周期
    year = models.IntegerField(
        "当前学年", default=int(datetime.now().strftime("%Y")))
    semester = models.CharField(
        "当前学期", choices=Semester.choices, max_length=15)

    scheduler = models.CharField("上课时间", max_length=25)
    classroom = models.CharField("上课地点", max_length=25)
    evaluation_manner = models.CharField("考核方式", max_length=225)
    education_plan = models.CharField("教学计划", max_length=225)

    def __str__(self):
        return str(self.cid)


class ActivityManager(models.Manager):
    def activated(self):
        # 选择学年相同，并且学期相同或者覆盖的
        return self.filter(year=int(local_dict["semester_data"]["year"])).filter(
            semester__contains=local_dict["semester_data"]["semester"]
        )

class Activity(models.Model):
    class Meta:
        verbose_name = "活动"
        verbose_name_plural = verbose_name
    
    '''
    Jul 30晚, Activity类经历了较大的更新, 请阅读群里[活动发起逻辑]文档，看一下活动发起需要用到的变量
    (1) 删除是否允许改变价格, 直接允许价格变动, 取消政策见文档【不允许投点的价格变动】
    (2) 取消活动报名时间的填写, 改为选择在活动结束前多久结束报名，选项见EndBefore
    (3) 活动容量[capacity]允许是正无穷
    (4) 增加活动状态类, 恢复之前的活动状态记录方式, 通过定时任务来改变 #TODO
    (5) 除了定价方式[bidding]之外的量都可以改变, 其中[capicity]不能低于目前已经报名人数, 活动的开始时间不能早于当前时间+1h
    (6) 修改活动时间同步导致报名时间的修改, 当然也需要考虑EndBefore的修改; 这部分修改通过定时任务的时间体现, 详情请见地下室schedule任务的新建和取消
    (7) 增加活动管理的接口, activated, 筛选出这个学期的活动(见class [ActivityManager])

    '''

    title = models.CharField("活动名称", max_length=25)
    organization_id = models.ForeignKey(
        Organization,
        # to_field="organization_id", 删除掉to_field, 保持纯净对象操作
        on_delete=models.CASCADE,
    )
    year = models.IntegerField("活动年份", default=int(local_dict["semester_data"]["year"]))
    semester = models.CharField("活动学期", choices=Semester.choices, max_length=15, default=Semester.get(local_dict["semester_data"]["semester"]))
    publish_time = models.DateTimeField("信息发布时间", auto_now_add=True)  # 可以为空
    
    # 删除显示报名时间, 保留一个字段表示报名截止于活动开始前多久：1h / 1d / 3d / 7d
    class EndBefore(models.IntegerChoices):
        onehour = (0, "一小时")
        oneday = (1,"一天")
        threeday = (2,"三天")
        oneweek = (3,"一周")

    class EndBeforeHours:
        prepare_times = [1, 24, 72, 168]
    
    endbefore = models.SmallIntegerField("报名截止于", choices=EndBefore.choices, default= EndBefore.oneday)
    start = models.DateTimeField("活动开始时间", blank=True, default=datetime.now)
    end = models.DateTimeField("活动结束时间", blank=True, default=datetime.now)
    # prepare_time = models.FloatField("活动准备小时数", default=24.0)
    # apply_start = models.DateTimeField("报名开始时间", blank=True, default=datetime.now)

    location = models.CharField("活动地点", blank=True, max_length=200)
    introduction = models.TextField("活动简介", max_length=225, blank=True)
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)  # 二维码字段

    # url,活动二维码

    bidding = models.BooleanField("是否投点竞价", default=False)
    YQPoint = models.FloatField("元气值定价/投点基础价格", default=0.0)
    budget = models.FloatField("预算", default=0.0)



    # 允许是正无穷, 可以考虑用INTINF
    capacity = models.IntegerField("活动最大参与人数", default=100)
    current_participants = models.IntegerField("活动当前报名人数", default=0)
    
    URL = models.URLField("活动相关(推送)网址", null=True, blank=True)

    def __str__(self):
        return f"活动：{self.title}"

    class Status(models.TextChoices):
        REVIEWING = "审核中"
        CANCELED = "已取消"
        APPLYING = "报名中"
        WAITING = "等待中"
        PROGRESSING = "进行中"
        END = "已结束"

    # 恢复活动状态的类别
    status = models.CharField(
        "活动状态", choices=Status.choices, default=Status.APPLYING, max_length=32
    )

    objects = ActivityManager()

    def save(self, *args, **kwargs):
        self.YQPoint = round(self.YQPoint, 1)
        super(Activity, self).save(*args, **kwargs)


class TransferRecord(models.Model):
    class Meta:
        verbose_name = "转账信息"
        verbose_name_plural = verbose_name
        ordering = ["-finish_time", "-start_time"]

    proposer = models.ForeignKey(
        User, related_name="send_trans", on_delete=models.CASCADE
    )
    recipient = models.ForeignKey(
        User, related_name="recv_trans", on_delete=models.CASCADE
    )
    amount = models.FloatField("转账元气值数量", default=0)
    start_time = models.DateTimeField("发起时间", auto_now_add=True)
    finish_time = models.DateTimeField("处理时间", blank=True, null=True)
    message = models.CharField("备注信息", max_length=255, default="")

    corres_act = models.ForeignKey(
        Activity, on_delete=models.SET_NULL, null=True, blank=True
    )

    class TransferStatus(models.IntegerChoices):
        ACCEPTED = (0, "已接收")
        WAITING = (1, "待确认")
        REFUSED = (2, "已拒绝")
        SUSPENDED = (3, "已终止")
        REDUND = (4, "已退回")

    status = models.SmallIntegerField(
        choices=TransferStatus.choices, default=1)

    def save(self, *args, **kwargs):
        self.amount = round(self.amount, 1)
        super(TransferRecord, self).save(*args, **kwargs)


class Participant(models.Model):
    class Meta:
        verbose_name = "活动参与情况"
        verbose_name_plural = verbose_name
        ordering = ["activity_id"]

    activity_id = models.ForeignKey(Activity, on_delete=models.CASCADE)
    person_id = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE)

    class AttendStatus(models.IntegerChoices):
        APPLYING = 0  # 申请中
        APLLYFAILED = 1  # 申请失败
        APLLYSUCCESS = 2  # 已报名
        ATTENDED = 3  # 已参与
        UNATTENDED = 4  # 未参与
        CANCELED = 5  # 放弃，如果学生取消活动，则设置这里

    status = models.IntegerField('学生参与活动状态', choices=AttendStatus.choices, default=0)


class YQPointDistribute(models.Model):
    class DistributionType(models.IntegerChoices):
        # 定期发放的类型
        # 每类型各最多有一个status为Yes的实例
        TEMPORARY = (0, "临时发放")
        WEEK = (1, "每周发放一次")
        TWO_WEEK = (2, "每两周发放一次")
        SEMESTER = (26, "每学期发放一次") # 一年有52周
    
    # 发放元气值的上限，多于此值则不发放
    per_max_dis_YQP = models.FloatField("自然人发放元气值上限")
    org_max_dis_YQP = models.FloatField("组织发放元气值上限")
    # 个人和组织所能平分的元气值比例
    # 发放时，从学院剩余元气值中，抽取向自然人分发的比例，平分给元气值低于上限的自然人；组织同理
    per_YQP = models.FloatField("自然人获得的元气值", default=0)
    org_YQP = models.FloatField("组织获得的元气值", default=0)

    start_time = models.DateTimeField("开始时间")

    status = models.BooleanField("是否应用", default=False)
    type = models.IntegerField("发放类型", choices=DistributionType.choices)

    class Meta:
        verbose_name = "元气值发放"
        verbose_name_plural = verbose_name


class Notification(models.Model):
    class Meta:
        verbose_name = "通知消息"
        verbose_name_plural = verbose_name
        ordering = ["id"]

    receiver = models.ForeignKey(
        User, related_name="recv_notice", on_delete=models.CASCADE
    )
    sender = models.ForeignKey(
        User, related_name="send_notice", on_delete=models.CASCADE
    )
    class NotificationStatus(models.IntegerChoices):
        DONE = (0, "已处理")
        UNDONE = (1, "待处理")

    class NotificationType(models.IntegerChoices):
        NEEDREAD = (0, '知晓类')    # 只需选择“已读”即可
        NEEDDO = (1, '处理类')      # 需要处理的事务

    class NotificationTitle(models.IntegerChoices):
        # 等待逻辑补充
        TRANSFER_CONFIRM = (0, '转账确认通知')
        ACTIVITY_INFORM = (1, '活动状态通知')
        VERIFY_INFORM = (2, '审核信息通知')
        PERSITION_INFORM = (3, '人事变动通知')

    status = models.SmallIntegerField(choices=NotificationStatus.choices, default=1)
    title = models.SmallIntegerField(choices=NotificationTitle.choices, blank=True, null=True)
    content = models.CharField("通知内容", max_length=225, blank=True)
    start_time = models.DateTimeField("通知发出时间", auto_now_add=True)
    finish_time = models.DateTimeField("通知处理时间", blank=True, null=True)
    type = models.SmallIntegerField(choices=NotificationType.choices, default=0)
    
    URL = models.URLField("相关网址", null=True, blank=True)
