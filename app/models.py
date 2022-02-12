from django.db import models, transaction
from django_mysql.models import ListCharField
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from datetime import datetime, timedelta
from boottest import local_dict
from django.conf import settings
from random import choice


__all__ = [
    'User',
    'NaturalPerson',
    'Freshman',
    'OrganizationType',
    'OrganizationTag',
    # 'Semester',
    'Organization',
    'Position',
    'Course',
    'CommentBase',
    'Activity',
    'ActivityPhoto',
    'TransferRecord',
    'Participant',
    'YQPointDistribute',
    'QandA',
    'Notification',
    'Comment',
    'CommentPhoto',
    'ModifyOrganization',
    'ModifyPosition',
    'Reimbursement',
    'ReimbursementPhoto',
    'Help',
    'Wishes',
    'ModifyRecord',
    'Course',
    'CourseTime',
    'CourseParticipant',
    'CourseRecord',
    'PageLog',
    'ModuleLog',
]


def current_year()-> int:
    return int(datetime.now().strftime("%Y"))

class NaturalPersonManager(models.Manager):
    def activated(self):
        return self.exclude(status=NaturalPerson.GraduateStatus.GRADUATED)

    def autoset_status_annually(self):  # 修改毕业状态，每年调用一次
        year = current_year() - 4
        self.activated().filter(stu_grade=str(year)).update(GraduateStatus=1)

    def set_status(self, **kwargs):  # 延毕情况后续实现
        pass

    def teachers(self):
        return self.filter(identity=NaturalPerson.Identity.TEACHER)


class NaturalPerson(models.Model):
    class Meta:
        verbose_name = "自然人"
        verbose_name_plural = verbose_name

    # Common Attributes
    person_id = models.OneToOneField(to=User, on_delete=models.CASCADE)
    
    # 不要在任何地方使用此字段，建议先删除unique进行迁移，然后循环调用save
    stu_id_dbonly = models.CharField("学号——仅数据库", max_length=150,
                                    blank=True)

    name = models.CharField("姓名", max_length=10)
    nickname = models.CharField("昵称", max_length=20, null=True, blank=True)

    class Gender(models.IntegerChoices):
        MALE = (0, "男")
        FEMALE = (1, "女")

    gender = models.SmallIntegerField(
        "性别", choices=Gender.choices, null=True, blank=True
    )

    birthday = models.DateField("生日", null=True, blank=True)
    email = models.EmailField("邮箱", null=True, blank=True)
    telephone = models.CharField("电话", max_length=20, null=True, blank=True)
    biography = models.TextField("自我介绍", max_length=1024, default="还没有填写哦～")
    avatar = models.ImageField(upload_to=f"avatar/", blank=True)
    wallpaper = models.ImageField(upload_to=f"wallpaper/", blank=True)
    first_time_login = models.BooleanField("首次登录", default=True)
    inform_share = models.BooleanField(default=True) # 是否第一次展示有关分享的帮助
    last_time_login = models.DateTimeField("上次登录时间", blank=True, null=True)
    objects = NaturalPersonManager()
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)
    visit_times = models.IntegerField("浏览次数",default=0) # 浏览主页的次数

    YQPoint_Bonus = models.FloatField("待发放元气值", default=0)
    YQPoint = models.FloatField("元气值余额", default=0)
    bonusPoint = models.FloatField("积分", default=0)

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
        UNDERGRADUATED = (0, "未毕业")
        GRADUATED = (1, "已毕业")

    status = models.SmallIntegerField("在校状态", choices=GraduateStatus.choices, default=0)

    # 表示信息是否选择展示
    # '昵称','性别','邮箱','电话','专业','宿舍'
    show_nickname = models.BooleanField(default=False)
    show_birthday = models.BooleanField(default=False)
    show_gender = models.BooleanField(default=True)
    show_email = models.BooleanField(default=False)
    show_tel = models.BooleanField(default=False)
    show_major = models.BooleanField(default=True)
    show_dorm = models.BooleanField(default=False)

    # 注意：这是不订阅的列表！！
    unsubscribe_list = models.ManyToManyField(
        "Organization", related_name="unsubscribers", db_index=True
    )

    class ReceiveLevel(models.IntegerChoices):
        # DEBUG = (-1000, '全部')
        MORE = (0, '更多')
        LESS = (500, '更少')
        # FATAL_ONLY = (1000, '仅重要')
        # NONE = (1001, '不接收')
    
    wechat_receive_level = models.IntegerField(
        '微信接收等级',
        choices=ReceiveLevel.choices, default=0,
        help_text='允许微信接收的最低消息等级，更低等级的通知类消息将被屏蔽'
        )

    accept_promote = models.BooleanField(default=True)    # 是否接受推广消息
    active_score = models.FloatField("活跃度", default=0)  # 用户活跃度

    def __str__(self):
        return str(self.name)

    def get_user_ava(self):
        try:
            avatar = self.avatar
        except:
            avatar = ""
        if not avatar:
            avatar = "avatar/person_default.jpg"
        return settings.MEDIA_URL + str(avatar)

    def show_info(self):
        """
            返回值为一个列表，在search.html中使用，按照如下顺序呈现：
            people_field = ['姓名', '年级', '班级', '专业', '状态']
            其中未公开的属性呈现为‘未公开’
            注意：major, gender, nickname, email, tel, dorm可能为None
            班级和年级现在好像也可以为None
        """
        gender = ["男", "女"]
        info = [self.name]
        info.append(self.nickname if (self.show_nickname) else "未公开")
        
        info += [self.stu_grade, self.stu_class]
        # info.append(self.nickname if (self.show_nickname) else unpublished)
        # info.append(
        #    unpublished if ((not self.show_gender) or (self.gender == None)) else gender[self.gender])
        info.append(self.stu_major if (self.show_major) else "未公开")
        # info.append(self.email if (self.show_email) else unpublished)
        # info.append(self.telephone if (self.show_tel) else unpublished)
        # info.append(self.stu_dorm if (self.show_dorm) else unpublished)

        info.append(
            "在校"
            if self.status == NaturalPerson.GraduateStatus.UNDERGRADUATED
            else "已毕业"
        )

        return info

    def save(self, *args, **kwargs):
        if not self.stu_id_dbonly:
            self.stu_id_dbonly = self.person_id.username
        else:
            assert self.stu_id_dbonly == self.person_id.username, "学号不匹配！"
        self.YQPoint = round(self.YQPoint, 1)
        self.bonusPoint = round(self.bonusPoint, 1)
        super().save(*args, **kwargs)


class Freshman(models.Model):
    class Meta:
        verbose_name = "新生信息"
        verbose_name_plural = verbose_name

    sid = models.CharField("学号", max_length=20, unique=True)
    name = models.CharField("姓名", max_length=10)
    gender = models.CharField("性别", max_length=5)
    birthday = models.DateField("生日")
    place = models.CharField("生源地", default="其它", max_length=32, blank=True)

    class Status(models.IntegerChoices):
        UNREGISTERED = (0, "未注册")
        REGISTERED = (1, "已注册")
    
    grade = models.CharField("年级", max_length=5, null=True, blank=True)
    status = models.SmallIntegerField("注册状态", choices=Status.choices, default=0)

    def exists(self):
        user_exist = User.objects.filter(username=self.sid).exists()
        person_exist = NaturalPerson.objects.filter(person_id__username=self.sid).exists()
        return "person" if person_exist else(
                "user" if user_exist else "")


class OrganizationType(models.Model):
    class Meta:
        verbose_name = "小组类型"
        verbose_name_plural = verbose_name
        ordering = ["otype_name"]

    otype_id = models.SmallIntegerField("小组类型编号", unique=True, primary_key=True)
    otype_name = models.CharField("小组类型名称", max_length=25)
    otype_superior_id = models.SmallIntegerField("上级小组类型编号", default=0)
    incharge = models.ForeignKey(
        NaturalPerson,
        related_name="incharge",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )  # 相关小组的负责人
    job_name_list = ListCharField(
        base_field=models.CharField(max_length=10), size=4, max_length=44
    )  # [部长, 副部长, 部员]

    allow_unsubscribe = models.BooleanField("允许取关?", default=True)

    control_pos_threshold = models.SmallIntegerField("管理者权限等级上限",default = 0)

    def __str__(self):
        return str(self.otype_name)

    def get_name(self, pos: int):
        if pos >= len(self.job_name_list):
            return "成员"
        return self.job_name_list[pos]

    def get_pos_from_str(self, pos_name):  # 若非列表内的名字，返回最低级
        if not pos_name in self.job_name_list:
            return len(self.job_name_list)
        return self.job_name_list.index(pos_name)

    def get_length(self):
        return len(self.job_name_list) + 1

class Semester(models.TextChoices):
    FALL = "Fall"
    SPRING = "Spring"
    ANNUAL = "Fall+Spring"

    def get(
        semester,
    ):  # read a string indicating the semester, return the correspoding status
        if semester == "Fall":
            return Semester.FALL
        elif semester == "Spring":
            return Semester.SPRING
        elif semester == "Annual":
            return Semester.ANNUAL
        else:
            raise NotImplementedError("出现未设计的学期状态")


class OrganizationTag(models.Model):
    class Meta:
        verbose_name = "组织类型标签"
        verbose_name_plural = verbose_name
    
    name = models.CharField("标签名", max_length=10, blank=False)


class OrganizationManager(models.Manager):
    def activated(self):
        return self.exclude(status=False)


class Organization(models.Model):
    class Meta:
        verbose_name = "小组"
        verbose_name_plural = verbose_name

    organization_id = models.OneToOneField(to=User, on_delete=models.CASCADE)
    oname = models.CharField(max_length=32, unique=True)
    otype = models.ForeignKey(OrganizationType, on_delete=models.CASCADE)
    status = models.BooleanField("激活状态", default=True)  # 表示一个小组是否上线(或者是已经被下线)

    objects = OrganizationManager()

    YQPoint = models.FloatField("元气值", default=0.0)
    introduction = models.TextField("介绍", null=True, blank=True, default="这里暂时没有介绍哦~")
    avatar = models.ImageField(upload_to=f"avatar/", blank=True)
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)  # 二维码字段
    wallpaper = models.ImageField(upload_to=f"wallpaper/", blank=True)
    visit_times = models.IntegerField("浏览次数",default=0) # 浏览主页的次数

    first_time_login = models.BooleanField(default=True)  # 是否第一次登录
    inform_share = models.BooleanField(default=True) # 是否第一次展示有关分享的帮助
        
    # 组织类型标签，一个组织可能同时有多个标签
    tags = models.ManyToManyField(OrganizationTag)

    def __str__(self):
        return str(self.oname)

    def save(self, *args, **kwargs):
        self.YQPoint = round(self.YQPoint, 1)
        super().save(*args, **kwargs)

    def get_user_ava(self):
        try:
            avatar = self.avatar
        except:
            avatar = ""
        if not avatar:
            avatar = "avatar/org_default.png"
        return settings.MEDIA_URL + str(avatar)
    
    def get_subscriber_num(self, activated=True):
        if activated:
            return NaturalPerson.objects.activated().exclude(
                id__in=self.unsubscribers.all()).count()
        return NaturalPerson.objects.all().count() - self.unsubscribers.count()

    def get_neg_unsubscriber_num(self, activated=True):
        if activated:
            return -NaturalPerson.objects.activated().filter(
                id__in=self.unsubscribers.all()).count()
        return -self.unsubscribers.count()


class PositionManager(models.Manager):
    def current(self):
        return self.filter(
            in_year=int(local_dict["semester_data"]["year"]),
            in_semester__contains=local_dict["semester_data"]["semester"],
        )

    def activated(self):
        return self.current().filter(status=Position.Status.INSERVICE)

    def create_application(self, person, org, apply_type, apply_pos):
        raise NotImplementedError('该函数已废弃')
        warn_duplicate_message = "There has already been an application of this state!"
        with transaction.atomic():
            if apply_type == "JOIN":
                apply_type = Position.ApplyType.JOIN
                assert len(self.activated().filter(person=person, org=org)) == 0
                application, created = self.current().get_or_create(
                    person=person, org=org, apply_type=apply_type, apply_pos=apply_pos
                )
                assert created, warn_duplicate_message
            elif apply_type == "WITHDRAW":
                application = (
                    self.current()
                    .select_for_update()
                    .get(person=person, org=org, status=Position.Status.INSERVICE)
                )
                assert (
                    application.apply_type != Position.ApplyType.WITHDRAW
                ), warn_duplicate_message
                application.apply_type = Position.ApplyType.WITHDRAW
            elif apply_type == "TRANSFER":
                application = (
                    self.current()
                    .select_for_update()
                    .get(person=person, org=org, status=Position.Status.INSERVICE)
                )
                assert (
                    application.apply_type != Position.ApplyType.TRANSFER
                ), warn_duplicate_message
                application.apply_type = Position.ApplyType.TRANSFER
                application.apply_pos = int(apply_pos)
                assert (
                    application.apply_pos < application.pos
                ), "TRANSFER must apply for higher position!"
            else:
                raise ValueError(
                    f"Not available attributes for apply_type: {apply_type}"
                )
            application.apply_status = Position.ApplyStatus.PENDING
            application.save()
            return apply_type, application


class Position(models.Model):
    """ 职务
    职务相关：
        - person: 自然人
        - org: 小组
        - pos: 职务等级
        - status: 职务状态
        - show_post: 是否公开职务
        - in_year: 学年
        - in_semester: 学期
    成员变动申请相关：
        - apply_type: 申请类型
        - apply_status: 申请状态
        - apply_pos: 申请职务等级
    """

    class Meta:
        verbose_name = "职务"
        verbose_name_plural = verbose_name

    person = models.ForeignKey(
        NaturalPerson, related_name="position_set", on_delete=models.CASCADE,
    )
    org = models.ForeignKey(
        Organization, related_name="position_set", on_delete=models.CASCADE,
    )

    # 职务的逻辑应该是0最高，1次之这样，然后数字映射到名字是在小组类型表中体现的
    # 10 没有特定含义，只表示最低等级
    pos = models.SmallIntegerField(verbose_name="职务等级", default=10)

    # 是否有管理权限，默认值为 pos <= otype.control_pos_threshold, 可以被覆盖
    is_admin = models.BooleanField("是否是负责人", default = 0)

    # 是否选择公开当前的职务
    show_post = models.BooleanField(default=True)

    # 表示是这个小组哪一年、哪个学期的成员
    in_year = models.IntegerField("当前学年", default=current_year)
    in_semester = models.CharField(
        "当前学期", choices=Semester.choices, default=Semester.ANNUAL, max_length=15
    )

    class Status(models.TextChoices):  # 职务状态
        INSERVICE = "在职"
        DEPART = "离职"
        # NONE = "无职务状态"  # 用于第一次加入小组申请

    status = models.CharField(
        "职务状态", choices=Status.choices, max_length=32, default=Status.INSERVICE
    )

    '''
    class ApplyType(models.TextChoices):  # 成员变动申请类型
        JOIN = "加入小组"
        WITHDRAW = "退出小组"
        TRANSFER = "修改职位"
        NONE = "无申请流程"  # 指派职务
    apply_type = models.CharField(
        "申请类型", choices=ApplyType.choices, max_length=32, default=ApplyType.NONE
    )
    class ApplyStatus(models.TextChoices):  # 成员变动申请状态
        PENDING = "等待中"
        PASS = "已通过"
        REJECT = "未通过"
        NONE = ""  # 对应“无申请流程”
    
    apply_status = models.CharField(
        "申请状态", choices=ApplyStatus.choices, max_length=32, default=ApplyStatus.NONE
    )
    apply_pos = models.SmallIntegerField(verbose_name="申请职务等级", default=10)
    '''
    objects = PositionManager()

    def get_pos_number(self): #返回对应的pos number 并作超出处理
        return min(len(self.org.otype.job_name_list), self.pos)


class ActivityManager(models.Manager):
    def activated(self, only_displayable=True):
        # 选择学年相同，并且学期相同或者覆盖的
        # 请保证query_range是一个queryset，将manager的行为包装在query_range计算完之前
        if only_displayable:
            query_range = self.displayable()
        else:
            query_range = self.all()
        return query_range.filter(year=int(local_dict["semester_data"]["year"])).filter(
            semester__contains=local_dict["semester_data"]["semester"]
        )

    def displayable(self):
        # REVIEWING, ABORT 状态的活动，只对创建者和审批者可见，对其他人不可见
        # 过审后被取消的活动，还是可能被看到，也应该让学生看到这个活动被取消了
        return self.exclude(status__in=[
            Activity.Status.REVIEWING,
            # Activity.Status.CANCELED,
            Activity.Status.ABORT,
            Activity.Status.REJECT
        ])

    def get_newlyended_activity(self):
        # 一周内结束的活动
        nowtime = datetime.now()
        mintime = nowtime - timedelta(days = 7)
        return self.activated().filter(end__gt = mintime).filter(status=Activity.Status.END)

    def get_recent_activity(self):
        # 开始时间在前后一周内，除了取消和审核中的活动。按时间逆序排序
        nowtime = datetime.now()
        mintime = nowtime - timedelta(days = 7)
        maxtime = nowtime + timedelta(days = 7)
        return self.activated().filter(start__gt = mintime).filter(start__lt = maxtime).filter(
            status__in=[
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING,
                Activity.Status.END
            ]
        ).order_by("-start")

    def get_newlyreleased_activity(self):
        # 最新一周内发布的活动，按发布的时间逆序
        nowtime = datetime.now()
        return self.activated().filter(publish_time__gt = nowtime - timedelta(days = 7)).filter(
            status__in=[
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING
            ]
        ).order_by("-publish_time")

    def get_today_activity(self):
        # 开始时间在今天的活动,且不展示结束的活动。按开始时间由近到远排序
        nowtime = datetime.now()
        return self.filter(year=int(local_dict["semester_data"]["year"])).filter(
            semester__contains=local_dict["semester_data"]["semester"]
        ).filter(
            status__in=[
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING,
            ]
        ).filter(start__year=nowtime.year
        ).filter(start__month=nowtime.month
        ).filter(start__day=nowtime.day
        ).order_by("start")
        

class CommentBase(models.Model):
    '''
    带有评论的模型基类
    子类必须重载save()保存typename，值必须为类名的小写版本或类名
    子类如果希望直接使用聚合页面呈现模板，应该定义__str__方法
    默认的呈现内容为：实例名称、创建时间、上次修改时间
    如果希望呈现审核页面，如审核中、创建者信息，则应该分别定义get_status_display和get_poster_name
    其中，如果你的status是一个枚举字段，则无需定义get_status_display
        status的display建议为：
            包含“未/不/拒绝”的表示失败
            此外包含“通过/接受”的表示审核通过
            包含“修改”的为需要修改（可能用不到）
            包含“取消”的为自己取消
            其他都默认呈现“审核中”，可以自行修改html模板增加状态
    如果你希望呈现更多信息，应该定义extra_display，返回一个二或三元组构成的列表
        (键, 值, 图标名="envelope-o")将被渲染为一行[图标]键：值
        图标名请参考fontawesome的图标类名
    '''
    class Meta:
        verbose_name = "带有评论"
        verbose_name_plural = verbose_name

    id = models.AutoField(primary_key=True)  # 自增ID，标识唯一的基类信息
    typename = models.CharField("模型类型", max_length=32, default="commentbase")   # 子类信息
    time = models.DateTimeField("发起时间", auto_now_add=True)
    modify_time = models.DateTimeField("上次修改时间", auto_now=True) # 每次评论自动更新

    def get_instance(self):
        if self.typename.lower() == 'commentbase':
            return self
        try:
            return getattr(self, self.typename.lower())
        except:
            return self


class Activity(CommentBase):
    class Meta:
        verbose_name = "活动"
        verbose_name_plural = verbose_name

    """
    Jul 30晚, Activity类经历了较大的更新, 请阅读群里[活动发起逻辑]文档，看一下活动发起需要用到的变量
    (1) 删除是否允许改变价格, 直接允许价格变动, 取消政策见文档【不允许投点的价格变动】
    (2) 取消活动报名时间的填写, 改为选择在活动结束前多久结束报名，选项见EndBefore
    (3) 活动容量[capacity]允许是正无穷
    (4) 增加活动状态类, 恢复之前的活动状态记录方式, 通过定时任务来改变 #TODO
    (5) 除了定价方式[bidding]之外的量都可以改变, 其中[capicity]不能低于目前已经报名人数, 活动的开始时间不能早于当前时间+1h
    (6) 修改活动时间同步导致报名时间的修改, 当然也需要考虑EndBefore的修改; 这部分修改通过定时任务的时间体现, 详情请见地下室schedule任务的新建和取消
    (7) 增加活动立项的接口, activated, 筛选出这个学期的活动(见class [ActivityManager])
    """

    title = models.CharField("活动名称", max_length=50)
    organization_id = models.ForeignKey(
        Organization,
        # to_field="organization_id", 删除掉to_field, 保持纯净对象操作
        on_delete=models.CASCADE,
    )

    year = models.IntegerField("活动年份", default=current_year)

    semester = models.CharField(
        "活动学期",
        choices=Semester.choices,
        max_length=15,
        default=Semester.get(local_dict["semester_data"]["semester"]),
    )

    publish_time = models.DateTimeField("信息发布时间", auto_now_add=True)  # 可以为空

    # 删除显示报名时间, 保留一个字段表示报名截止于活动开始前多久：1h / 1d / 3d / 7d
    class EndBefore(models.IntegerChoices):
        onehour = (0, "一小时")
        oneday = (1, "一天")
        threeday = (2, "三天")
        oneweek = (3, "一周")

    class EndBeforeHours:
        prepare_times = [1, 24, 72, 168]

    endbefore = models.SmallIntegerField(
        "报名截止于", choices=EndBefore.choices, default=EndBefore.oneday
    )

    apply_end = models.DateTimeField("报名截止时间", blank=True, default=datetime.now)
    start = models.DateTimeField("活动开始时间", blank=True, default=datetime.now)
    end = models.DateTimeField("活动结束时间", blank=True, default=datetime.now)
    # prepare_time = models.FloatField("活动准备小时数", default=24.0)
    # apply_start = models.DateTimeField("报名开始时间", blank=True, default=datetime.now)

    location = models.CharField("活动地点", blank=True, max_length=200)
    introduction = models.TextField("活动简介", max_length=225, blank=True)
    apply_reason = models.TextField("申请理由", max_length=225, blank=True)

    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)  # 二维码字段

    # url,活动二维码

    bidding = models.BooleanField("是否投点竞价", default=False)
    YQPoint = models.FloatField("元气值定价/投点基础价格", default=0.0)
    budget = models.FloatField("预算", default=0.0)

    need_checkin = models.BooleanField("是否需要签到", default=False)

    visit_times = models.IntegerField("浏览次数",default=0)

    examine_teacher = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE, verbose_name="审核老师")
    # recorded 其实是冗余，但用着方便，存了吧,activity_show.html用到了
    recorded = models.BooleanField("是否预报备", default=False)
    valid = models.BooleanField("是否已审核", default=False)

    inner = models.BooleanField("内部活动", default=False)

    class YQPointSource(models.IntegerChoices):
        COLLEGE = (0, "学院")
        STUDENT = (1, "学生")

    source = models.SmallIntegerField(
        "元气值来源", choices=YQPointSource.choices, default=1
    )

    # 允许是正无穷, 可以考虑用INTINF
    capacity = models.IntegerField("活动最大参与人数", default=100)
    current_participants = models.IntegerField("活动当前报名人数", default=0)

    URL = models.URLField("活动相关(推送)网址", max_length=1024, default="", blank=True)

    def __str__(self):
        return str(self.title)

    class Status(models.TextChoices):
        REVIEWING = "审核中"
        ABORT = "已撤销"
        REJECT = "未过审"
        CANCELED = "已取消"
        APPLYING = "报名中"
        WAITING = "等待中"
        PROGRESSING = "进行中"
        END = "已结束"

    # 恢复活动状态的类别
    status = models.CharField(
        "活动状态", choices=Status.choices, default=Status.REVIEWING, max_length=32
    )

    objects = ActivityManager()

    class ActivityCategory(models.IntegerChoices):
        NORMAL = (0, "普通活动")
        COURSE = (1, "课程活动")
        ELECTION = (2, "选课活动") # 不一定会使用到
    
    category = models.SmallIntegerField(
        "活动类别", choices=ActivityCategory.choices, default=0
    )

    def save(self, *args, **kwargs):
        self.YQPoint = round(self.YQPoint, 1)
        self.typename = "activity"
        super().save(*args, **kwargs)
    
    def popular_level(self, any_status=False):
        if not any_status and not self.status in [
            Activity.Status.WAITING,
            Activity.Status.PROGRESSING,
            Activity.Status.END,
        ]:
            return 0
        if self.current_participants >= self.capacity:
            return 2
        if (self.current_participants >= 30
            or (self.capacity >= 10 and self.current_participants >= self.capacity * 0.85)
            ):
            return 1
        return 0

    def has_tag(self):
        if self.need_checkin or self.inner:
            return True
        if self.status == Activity.Status.APPLYING:
            return True
        if self.popular_level():
            return True
        return False

class ActivityPhoto(models.Model):
    class Meta:
        verbose_name = "活动图片"
        verbose_name_plural = verbose_name
        ordering = ["-time"]

    class PhotoType(models.IntegerChoices):
        ANNOUNCE = (0, "预告图片")
        SUMMARY = (1, "总结图片")

    type = models.SmallIntegerField(choices=PhotoType.choices)
    image = models.ImageField(upload_to=f"activity/photo/%Y/%m/", verbose_name=u'活动图片', null=True, blank=True)
    activity = models.ForeignKey(Activity, related_name="photos", on_delete=models.CASCADE)
    time = models.DateTimeField("上传时间", auto_now_add=True)


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
        """
        对于活动来说：
        REFUND 由 ACCEPTED 而来
        SUSPENDED 由 PENDING 而来
        """
        ACCEPTED = (0, "已接收")
        WAITING = (1, "待确认")
        REFUSED = (2, "已拒绝")
        SUSPENDED = (3, "已终止")
        REFUND = (4, "已退回")
        PENDING = (5, "待审核")

    class TransferType(models.IntegerChoices):
        ACTIVITY = (0, "小组活动入账") # 包括像学院申请元气值的部分
        REIMBURSEMENT = (1, "报销兑换") # 元气值湮灭
        BONUS = (2, "学院发放") # 学院发放的奖励
        TRANSACTION = (3, "小组间转账")

    status = models.SmallIntegerField(choices=TransferStatus.choices, default=1)
    rtype = models.SmallIntegerField(choices=TransferType.choices, default=0)
    
    def save(self, *args, **kwargs):
        self.amount = round(self.amount, 1)
        super(TransferRecord, self).save(*args, **kwargs)


class ParticipantManager(models.Manager):
    def activated(self, no_unattend=False):
        '''返回成功报名的参与信息'''
        exclude_status = [
            Participant.AttendStatus.CANCELED,
            Participant.AttendStatus.APLLYFAILED,
        ]
        if no_unattend:
            exclude_status.append(Participant.AttendStatus.UNATTENDED)
        return self.exclude(status__in=exclude_status)

class Participant(models.Model):
    class Meta:
        verbose_name = "活动参与情况"
        verbose_name_plural = verbose_name
        ordering = ["activity_id"]

    activity_id = models.ForeignKey(Activity, on_delete=models.CASCADE)
    person_id = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE)

    class AttendStatus(models.TextChoices):
        APPLYING = "申请中"
        APLLYFAILED = "活动申请失败"
        APLLYSUCCESS = "已报名"
        ATTENDED = "已参与"
        UNATTENDED = "未签到"
        CANCELED = "放弃"

    status = models.CharField(
        "学生参与活动状态",
        choices=AttendStatus.choices,
        default=AttendStatus.APPLYING,
        max_length=32,
    )
    objects = ParticipantManager()


class YQPointDistribute(models.Model):
    class DistributionType(models.IntegerChoices):
        # 定期发放的类型
        # 每类型各最多有一个status为Yes的实例
        TEMPORARY = (0, "临时发放")
        WEEK = (1, "每周发放一次")
        TWO_WEEK = (2, "每两周发放一次")
        SEMESTER = (26, "每学期发放一次")  # 一年有52周

    # 发放元气值的上限，多于此值则不发放
    per_max_dis_YQP = models.FloatField("自然人发放元气值上限")
    org_max_dis_YQP = models.FloatField("小组发放元气值上限")
    # 个人和小组所能平分的元气值比例
    # 发放时，从学院剩余元气值中，抽取向自然人分发的数量，平分给元气值低于上限的自然人；小组同理
    per_YQP = models.FloatField("自然人获得的元气值", default=0)
    org_YQP = models.FloatField("小组获得的元气值", default=0)

    start_time = models.DateTimeField("开始时间")

    status = models.BooleanField("是否应用", default=False)
    type = models.IntegerField("发放类型", choices=DistributionType.choices)

    class Meta:
        verbose_name = "元气值发放"
        verbose_name_plural = verbose_name

class QandAManager(models.Manager):
    def activated(self, sender_flag=False, receiver_flag=False):
        if sender_flag:
            return self.exclude(status__in=[QandA.Status.IGNORE_SENDER,QandA.Status.DELETE])
        if receiver_flag:
            return self.exclude(status__in=[QandA.Status.IGNORE_RECEIVER,QandA.Status.DELETE])
        return self.exclude(status=QandA.Status.DELETE)

class QandA(models.Model):
    # 问答类
    class Meta:
        verbose_name = "问答记录"
        verbose_name_plural = verbose_name
    sender = models.ForeignKey(User, on_delete=models.SET_NULL,
                             related_name="send_QA_set", blank=True, null=True)
    receiver = models.ForeignKey(User, on_delete=models.SET_NULL,
                             related_name="receive_QA_set", blank=True, null=True)
    Q_time = models.DateTimeField('提问时间', auto_now_add=True)
    A_time = models.DateTimeField('回答时间', blank=True, null=True)
    Q_text = models.TextField('提问内容', default='', blank=True)
    A_text = models.TextField('回答内容', default='', blank=True)
    anonymous_flag = models.BooleanField("是否匿名", default=False)

    class Status(models.IntegerChoices):
        DONE = (0, "已回答")
        UNDONE = (1, "待回答")
        DELETE = (2, "已删除")
        IGNORE_SENDER = (3, "发送者忽略")
        IGNORE_RECEIVER = (4, "接收者忽略")
    
    status = models.SmallIntegerField(choices=Status.choices, default=1)
    
    objects = QandAManager()

class NotificationManager(models.Manager):
    def activated(self):
        return self.exclude(status=Notification.Status.DELETE)

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

    class Status(models.IntegerChoices):
        DONE = (0, "已处理")
        UNDONE = (1, "待处理")
        DELETE = (2, "已删除")

    class Type(models.IntegerChoices):
        NEEDREAD = (0, "知晓类")  # 只需选择“已读”即可
        NEEDDO = (1, "处理类")  # 需要处理的事务

    class Title(models.TextChoices):
        # 等待逻辑补充，可以自定义
        TRANSFER_CONFIRM = "转账确认通知"
        ACTIVITY_INFORM = "活动状态通知"
        VERIFY_INFORM = "审核信息通知"
        POSITION_INFORM = "成员变动通知"
        TRANSFER_FEEDBACK = "转账回执"
        NEW_ORGANIZATION = "新建小组通知"
        YQ_DISTRIBUTION = "元气值发放通知"
        PENDING_INFORM = "事务开始通知"


    status = models.SmallIntegerField(choices=Status.choices, default=1)
    title = models.CharField("通知标题", blank=True, null=True, max_length=50)
    content = models.TextField("通知内容", blank=True)
    start_time = models.DateTimeField("通知发出时间", auto_now_add=True)
    finish_time = models.DateTimeField("通知处理时间", blank=True, null=True)
    typename = models.SmallIntegerField(choices=Type.choices, default=0)
    URL = models.URLField("相关网址", null=True, blank=True, max_length=1024)
    bulk_identifier = models.CharField("批量信息标识", max_length=64, default="",
                                        db_index=True)
    anonymous_flag = models.BooleanField("是否匿名", default=False)
    relate_TransferRecord = models.ForeignKey(
        TransferRecord,
        related_name="transfer_notification",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    relate_instance = models.ForeignKey(
        CommentBase,
        related_name="relate_notifications",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    objects = NotificationManager()

    def get_title_display(self):
        return str(self.title)


class Comment(models.Model):
    class Meta:
        verbose_name = "评论"
        verbose_name_plural = verbose_name
        ordering = ["-time"]

    commentator = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="评论者")
    commentbase = models.ForeignKey(
        CommentBase, related_name="comments", on_delete=models.CASCADE
    )
    text = models.TextField("文字内容", default="", blank=True)
    time = models.DateTimeField("评论时间", auto_now_add=True)


class CommentPhoto(models.Model):
    class Meta:
        verbose_name = "评论图片"
        verbose_name_plural = verbose_name

    image = models.ImageField(
        upload_to=f"comment/%Y/%m/", verbose_name="评论图片", null=True, blank=True
    )
    comment = models.ForeignKey(
        Comment, related_name="comment_photos", on_delete=models.CASCADE
    )

    # 路径无法加上相应图片
    def imagepath(self):
        return settings.MEDIA_URL + str(self.image)


class ModifyOrganization(CommentBase):
    class Meta:
        verbose_name = "新建小组"
        verbose_name_plural = verbose_name
        ordering = ["-modify_time", "-time"]

    oname = models.CharField(max_length=32) #这里不设置unique的原因是可能是已取消
    otype = models.ForeignKey(OrganizationType, on_delete=models.CASCADE)
    introduction = models.TextField("介绍", null=True, blank=True, default="这里暂时没有介绍哦~")
    application = models.TextField(
        "申请理由", null=True, blank=True, default="这里暂时还没写申请理由哦~"
    )
    avatar = models.ImageField(
        upload_to=f"avatar/", verbose_name="小组头像",default="avatar/org_default.png",null=True, blank=True
    )
    pos = models.ForeignKey(User, on_delete=models.CASCADE)

    class Status(models.IntegerChoices):  # 表示申请小组的请求的状态
        PENDING = (0, "审核中")
        CONFIRMED = (1, "已通过")  
        CANCELED = (2, "已取消")  
        REFUSED = (3, "已拒绝")

    status = models.SmallIntegerField(choices=Status.choices, default=0)
    
    def __str__(self):
        # YWolfeee: 不认为应该把类型放在如此重要的位置
        # return f'{self.oname}{self.otype.otype_name}'
        return f'新建小组{self.oname}的申请'

    def save(self, *args, **kwargs):
        self.typename = "neworganization"
        super().save(*args, **kwargs)

    def get_poster_name(self):
        try:
            person = NaturalPerson.objects.get(person_id=self.pos)
            return person.name
        except:
            return '未知'
    
    def extra_display(self):
        display = []
        if self.introduction and self.introduction != '这里暂时没有介绍哦~':
            display.append(('小组介绍', self.introduction))
        return display

    def get_user_ava(self):
        try:
            avatar = self.avatar
        except:
            avatar = ""
        if not avatar:
            avatar = "avatar/person_default.jpg"
        return settings.MEDIA_URL + str(avatar)
        
    def is_pending(self):   #表示是不是pending状态
        return self.status == ModifyOrganization.Status.PENDING


class ModifyPosition(CommentBase):
    class Meta:
        verbose_name = "成员申请详情"
        verbose_name_plural = verbose_name
        ordering = ["-modify_time", "-time"]

    # 我认为应该不去挂载这个外键，因为有可能没有，这样子逻辑会显得很复杂
    # 只有在修改被通过的一瞬间才修改Pisition类
    # 只有在创建的一瞬间对比Pisition检查状态是否合法（如时候是修改成员）
    #position = models.ForeignKey(
    #    to=Position, related_name="new_position", on_delete=models.CASCADE
    #)

    # 申请人
    person = models.ForeignKey(
        to = NaturalPerson, related_name = "position_application", on_delete = models.CASCADE
    )

    # 申请小组
    org = models.ForeignKey(
        to = Organization, related_name = "position_application", on_delete = models.CASCADE
    )

    # 申请职务等级
    pos = models.SmallIntegerField(verbose_name="申请职务等级", blank=True, null=True)
    

    reason = models.TextField(
        "申请理由", null=True, blank=True, default="这里暂时还没写申请理由哦~"
    )

    class Status(models.IntegerChoices):  # 表示申请成员的请求的状态
        PENDING = (0, "审核中")
        CONFIRMED = (1, "已通过")  
        CANCELED = (2, "已取消")  
        REFUSED = (3, "已拒绝")

    status = models.SmallIntegerField(choices=Status.choices, default=0)
    
    def __str__(self):
        return f'{self.org.oname}成员申请'

    class ApplyType(models.TextChoices):  # 成员变动申请类型
        JOIN = "加入小组"
        TRANSFER = "修改职位"
        WITHDRAW = "退出小组"
        # 指派职务不需要通过NewPosition类来实现
        # NONE = "无申请流程"  # 指派职务

    apply_type = models.CharField(
        "申请类型", choices=ApplyType.choices, max_length=32
    )


    def get_poster_name(self):
        try:
            return self.person
        except:
            return '未知'
    
    def extra_display(self):
        return self.reason

    def is_pending(self):   #表示是不是pending状态
            return self.status == ModifyPosition.Status.PENDING

    def accept_submit(self): #同意申请，假设都是合法操作
        if self.apply_type == ModifyPosition.ApplyType.WITHDRAW:
            Position.objects.activated().filter(
                org=self.org, person=self.person
            ).update(status=Position.Status.DEPART)
        elif self.apply_type == ModifyPosition.ApplyType.JOIN:
            # 尝试获取已有的position
            if Position.objects.current().filter(
                org=self.org, person=self.person).exists(): # 如果已经存在这个量了
                Position.objects.current().filter(org=self.org, person=self.person
                ).update(
                    status=Position.Status.INSERVICE,
                    pos=self.pos,
                    is_admin=(self.pos <= self.org.otype.control_pos_threshold))
            else: # 不存在 直接新建
                Position.objects.create(pos=self.pos, person=self.person, org=self.org, is_admin=(self.pos<=self.org.otype.control_pos_threshold))
        else:   # 修改 则必定存在这个量
            Position.objects.activated().filter(org=self.org, person=self.person
                ).update(pos=self.pos, is_admin=(self.pos <= self.org.otype.control_pos_threshold))
        # 修改申请状态
        ModifyPosition.objects.filter(id=self.id).update(status=ModifyPosition.Status.CONFIRMED)

    def save(self, *args, **kwargs):
        self.typename = "modifyposition"
        super().save(*args, **kwargs)


class Reimbursement(CommentBase):
    class Meta:
        verbose_name = "新建报销"
        verbose_name_plural = verbose_name
        ordering = ["-modify_time", "-time"]

    class ReimburseStatus(models.IntegerChoices):
        WAITING = (0, "待审核")

        CONFIRM1 = (1, "主管老师已确认")
        CONFIRM2 = (2, "财务老师已确认")

        CONFIRMED = (3, "已通过")
        # 如果需要更多审核，每个审核的确认状态应该是2的幂
        # 根据最新要求，最终不以线上为准，不再设置转账状态
        CANCELED = (4, "已取消")
        REFUSED = (5, "已拒绝")

    related_activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE
    )
    amount = models.FloatField("报销金额", default=0)
    message = models.TextField("备注信息", default="", blank=True)
    pos = models.ForeignKey(User, on_delete=models.CASCADE)#报销的小组
    status = models.SmallIntegerField(choices=ReimburseStatus.choices, default=0)
    record = models.ForeignKey(TransferRecord, on_delete=models.CASCADE) #转账信息的记录
    examine_teacher = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE, verbose_name="审核老师")
    def __str__(self):
        return f'{self.related_activity.title}活动报销'
        
    def save(self, *args, **kwargs):
        self.typename = "reimbursement"
        super().save(*args, **kwargs)

    def get_poster_name(self):
        try:
            org = Organization.objects.get(organization_id=self.pos)
            return org
        except:
            return '未知'

    def extra_display(self):
        display = []
        display.append(('报销金额', str(self.amount) + '元', 'money'))
        if self.message:
            display.append(('备注', self.message))
        return display

    def is_pending(self):   #表示是不是pending状态
        return self.status == Reimbursement.ReimburseStatus.WAITING

class ReimbursementPhoto(models.Model):
    class Meta:
        verbose_name = "报销相关图片"
        verbose_name_plural = verbose_name
        ordering = ["-time"]
    class PhotoType(models.IntegerChoices):
        MATERIAL = (0, "报销材料")  #如账单信息等
        SUMMARY = (1, "总结图片")   #待审核的活动总结图片
    type = models.SmallIntegerField(choices=PhotoType.choices)
    image = models.ImageField(upload_to=f"reimbursement/photo/%Y/%m/", verbose_name=u'报销相关图片', null=True, blank=True)
    related_reimb = models.ForeignKey(Reimbursement, related_name="reimbphotos", on_delete=models.CASCADE)
    time = models.DateTimeField("上传时间", auto_now_add=True)
    

class Help(models.Model):
    '''
        页面帮助类
    '''
    title = models.CharField("帮助标题", max_length=20, blank=False)
    content = models.TextField("帮助内容", max_length=500)

    class Meta:
        verbose_name = "页面帮助"
        verbose_name_plural = "页面帮助"

    def __str__(self) -> str:
        return self.title

class Wishes(models.Model):
    class Meta:
        verbose_name = "心愿"
        verbose_name_plural = verbose_name
        ordering = ["-time"]
    
    COLORS = [
        "#FDAFAB","#FFDAC1","#FAF1D6",
        "#B6E3E9","#B5EAD7","#E2F0CB",
    ]
    # 不要随便删 admin.py也依赖本随机函数
    def rand_color():
        return choice(Wishes.COLORS)

    text = models.TextField("心愿内容", default="", blank=True)
    time = models.DateTimeField("发布时间", auto_now_add=True)
    background = models.TextField("颜色编码", default=rand_color)


class ModifyRecord(models.Model):
    # 仅用作记录，之后大概会删除吧，所以条件都设得很宽松
    class Meta:
        verbose_name = "修改记录"
        verbose_name_plural = verbose_name
        ordering = ["-time"]
    user = models.ForeignKey(User, on_delete=models.SET_NULL,
                             related_name="modify_records",
                             to_field='username', blank=True, null=True)
    usertype = models.CharField('用户类型', max_length=16, default='', blank=True)
    name = models.CharField('名称', max_length=32, default='', blank=True)
    info = models.TextField('相关信息', default='', blank=True)
    time = models.DateTimeField('修改时间', auto_now_add=True)


class CourseManager(models.Manager):
    def activated(self):
        # 选择当前学期的开设课程
        # 不显示已撤销的课程信息
        return self.filter(
            year=int(local_dict["semester_data"]["year"]),
            semester=local_dict["semester_data"]["semester"]).exclude(
                status=Course.Status.ABORT)

    def selected(self, person: NaturalPerson):
        # 返回当前学生所选的所有课程
        # participant_set是对CourseParticipant的反向查询
        return self.activated().filter(participant_set__person=person,
                                       participant_set__status__in=[
                                           CourseParticipant.Status.SELECT,
                                           CourseParticipant.Status.SUCCESS,
                                       ])

    def unselected(self, person: NaturalPerson):
        # 返回当前学生没选或失败的所有课程
        return self.activated().filter(participant_set__person=person,
                                       participant_set__status__in=[
                                           CourseParticipant.Status.UNSELECT,
                                           CourseParticipant.Status.FAILED,
                                       ])


class Course(models.Model):
    """
    助教发布课程需要填写的信息
    """
    class Meta:
        verbose_name = "书院课程"
        verbose_name_plural = verbose_name
        ordering = ["id"]

    name = models.CharField("课程名称", max_length=60)
    organization = models.ForeignKey(Organization,
                                     on_delete=models.CASCADE,
                                     verbose_name="开课组织")

    year = models.IntegerField("开课年份", default=current_year)

    semester = models.CharField("开课学期",
                                choices=Semester.choices,
                                max_length=15,
                                default=Semester.get(
                                    local_dict["semester_data"]["semester"]))

    # 课程开设的周数
    times = models.SmallIntegerField("课程开设周数", default=7)
    classroom = models.CharField("预期上课地点",
                                 max_length=60,
                                 default="",
                                 blank=True)
    teacher = models.CharField("授课教师", max_length=48, default="", blank=True)

    # 不确定能否统一选课的情况，先用最保险的方法
    # 如果由助教填写，表单验证时要着重检查这一部分。预选结束时间和补退选开始时间不应该相隔太近。
    stage1_start = models.DateTimeField("预选开始时间", blank=True, null=True)
    stage1_end = models.DateTimeField("预选结束时间", blank=True, null=True)
    stage2_start = models.DateTimeField("补退选开始时间", blank=True, null=True)
    stage2_end = models.DateTimeField("补退选结束时间", blank=True, null=True)

    bidding = models.FloatField("意愿点价格", default=0.0)

    introduction = models.TextField("课程简介", blank=True, default="这里暂时没有介绍哦~")

    # 假定课程已经进行线下审核，暂定不需要二次审核

    class Status(models.IntegerChoices):
        # 预选前和预选结束到补退选开始都是WAITING状态
        ABORT = (0, "已撤销")
        WAITING = (1, "未开始选课")
        STAGE1 = (2, "预选")
        STAGE2 = (3, "补退选")
        END = (4, "已结束")

    status = models.SmallIntegerField("开课状态",
                                      choices=Status.choices,
                                      default=Status.WAITING)

    class CourseType(models.IntegerChoices):
        # 课程类型
        MORAL = (0, "德")
        INTELLECTUAL = (1, "智")
        PHYSICAL = (2, "体")
        AESTHETICS = (3, "美")
        LABOUR = (4, "劳")

    type = models.SmallIntegerField("课程类型", choices=CourseType.choices)

    capacity = models.IntegerField("课程容量", default=100)
    current_participants = models.IntegerField("当前选课人数", default=0)

    # 暂时只允许上传一张图片
    photo = models.ImageField(verbose_name="宣传图片",
                              upload_to=f"course/photo/%Y/",
                              blank=True)

    # 课程群二维码
    QRcode = models.ImageField(upload_to=f"course/QRcode/%Y/", 
                               blank=True, 
                               null=True) 
                                
    objects = CourseManager()

    def save(self, *args, **kwargs):
        self.bidding = round(self.bidding, 1)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CourseTime(models.Model):
    """
    记录课程每周的上课时间，同一课程可以对应多个上课时间
    """
    class Meta:
        verbose_name = "上课时间"
        verbose_name_plural = verbose_name
        ordering = ["start"]

    course = models.ForeignKey(Course,
                               on_delete=models.CASCADE,
                               related_name="time_set")

    # 开始时间和结束时间指的是一次课程的上课时间和下课时间
    # 需要提醒助教，填写的时间是第一周上课的时间，这影响到课程活动的统一开设。
    start = models.DateTimeField("开始时间")
    end = models.DateTimeField("结束时间")
    cur_week = models.IntegerField("已生成周数", default=0)
    end_week = models.IntegerField("总周数", default=1)


class CourseParticipant(models.Model):
    """
    学生的选课情况
    """
    class Meta:
        verbose_name = "课程报名情况"
        verbose_name_plural = verbose_name

    course = models.ForeignKey(Course,
                               on_delete=models.CASCADE,
                               related_name="participant_set")
    person = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE)

    class Status(models.IntegerChoices):
        SELECT = (0, "已选课")
        UNSELECT = (1, "未选课")
        SUCCESS = (2, "选课成功")
        FAILED = (3, "选课失败")

    status = models.SmallIntegerField(
        "选课状态",
        choices=Status.choices,
        default=Status.UNSELECT,
    )


class CourseRecord(models.Model):
    class Meta:
        verbose_name = "学时表"
        verbose_name_plural = verbose_name
    # TODO: task 5 hjb(Toseic) 2022/2/6 related_name后续可能还需要添加
    
    person = models.ForeignKey(
        NaturalPerson, on_delete=models.CASCADE,
    )
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True,
    )
    # 长度兼容组织和课程名
    extra_name = models.CharField("课程名称额外标注", max_length=60, blank=True)
    
    year = models.IntegerField("课程所在学年", default=current_year)
    semester = models.CharField(
        "课程所在学期",
        choices=Semester.choices, 
        default=Semester.get(local_dict["semester_data"]["semester"]), 
        max_length=15,
    )
    total_hours = models.FloatField("总计参加学时")
    attend_times = models.IntegerField("参加课程次数", default=0)

    def get_course_name(self):
        if self.course is not None:
            return str(self.course)
        return self.extra_name
    get_course_name.short_description = "课程名"


class PageLog(models.Model):
    # 统计Page类埋点数据(PV/PD)
    class Meta:
        verbose_name = "Page类埋点记录"
        verbose_name_plural = verbose_name

    class CountType(models.IntegerChoices):
        PV = 0, "Page View"
        PD = 1, "Page Disappear"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.IntegerField('事件类型', choices=CountType.choices)

    page = models.URLField('页面url', max_length=256, blank=True)
    time = models.DateTimeField('发生时间', default=datetime.now)
    platform = models.CharField('设备类型', max_length=32, null=True, blank=True)
    explore_name = models.CharField('浏览器类型', max_length=32, null=True, blank=True)
    explore_version = models.CharField('浏览器版本', max_length=32, null=True, blank=True)


class ModuleLog(models.Model):
    # 统计Module类埋点数据(MV/MC)
    class Meta:
        verbose_name = "Module类埋点记录"
        verbose_name_plural = verbose_name
        
    class CountType(models.IntegerChoices):
        MV = 2, "Module View"
        MC = 3, "Module Click"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.IntegerField('事件类型', choices=CountType.choices)

    page = models.URLField('页面url', max_length=256, blank=True)
    module_name = models.CharField('模块名称', max_length=64, blank=True)
    time = models.DateTimeField('发生时间', default=datetime.now)
    platform = models.CharField('设备类型', max_length=32, null=True, blank=True)
    explore_name = models.CharField('浏览器类型', max_length=32, null=True, blank=True)
    explore_version = models.CharField('浏览器版本', max_length=32, null=True, blank=True)
