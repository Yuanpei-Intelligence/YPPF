'''
models.py

- 用户模型
- 应用内模型
   - 字段
   - 方法
   - 模型常量
   - 模型性质
- 模型管理器

修改要求
- 模型
    - 如需导出, 在__all__定义
    - 外键和管理器必须进行类型注释`: Class`
    - 与User有一对一关系的实体类型, 需要定义get_type, get_user和get_display_name方法
        - get_type返回UTYPE常量，且可以作为类方法使用
        - 其它建议的方法
            - get_absolute_url: 返回呈现该对象的url，用于后台跳转等，默认是绝对地址
            - get_user_ava: 返回头像的url路径，名称仅暂定，可选支持作为类方法
        - 此外，还应在ClassifiedUser和constants.py中注册
    - 处于平等地位但内部实现不同的模型, 应定义同名接口方法用于导出同类信息
    - 仅供前端使用的方法，在注释中说明
    - 能被评论的模型, 应继承自CommentBase, 并参考其文档字符串要求
    - 性质
        - 模型更改应通过显式数据库操作，性质应是数据库之外的内容（或只读性质）
        - 通过方法或类方法定义，或使用只读的property，建议使用前者，更加直观
        - 若单一对象有确定的定时任务相对应，应添加related_job_ids
    ...
- 模型管理器
    - 不应导出
    - 若与学期有关，必须至少支持select_current的三类筛选
    - 与User有一对一关系的实体管理器, 需要定义get_by_user方法
        - get_by_user通过关联的User获取实例，至少支持update和activate
    ...

@Date 2022-03-11
'''
import random
from math import ceil
from datetime import datetime, timedelta
from typing import TypeAlias

from django.db import models, transaction
from django.db.models import Q, QuerySet, Sum
from django_mysql.models.fields import ListCharField
from typing_extensions import Self

from app.config import *
from generic.models import User, YQPointRecord
import utils.models.query as SQ
from utils.models.descriptor import (invalid_for_frontend,
                                     necessary_for_frontend)
from utils.models.semester import Semester, select_current

__all__ = [
    # 模型
    'User',
    'NaturalPerson',
    'Person',
    'OrganizationType',
    'OrganizationTag',
    'Semester',
    'Organization',
    'Position',
    'CommentBase',
    'Notification',
    'Comment',
    'CommentPhoto',
    'ModifyOrganization',
    'ModifyPosition',
    'Help',
    'Wishes',
    'ModifyRecord',
]


def current_year():
    return GLOBAL_CONFIG.acadamic_year


def current_semester():
    return GLOBAL_CONFIG.semester


def image_url(image, enable_abs=False) -> str:
    '''不导出的函数，返回类似/media/path的url相对路径'''
    # ImageField将None和空字符串都视为<ImageFieldFile: None>
    # 即django.db.models.fields.files.ImageFieldFile对象
    # 该类有以下属性：
    # __str__: 返回一个字符串，与数据库表示相匹配，None会被转化为''
    # url: 非空时返回MEDIA_URL + str(self)， 否则抛出ValueError
    # path: 文件的绝对路径，可以是绝对路径但文件必须从属于MEDIA_ROOT，否则报错
    # enable_abs将被废弃
    path = str(image)
    if enable_abs and path.startswith('/'):
        return path
    return MEDIA_URL + path


class ClassifiedUser(models.Model):
    '''
    已分类的抽象用户模型，定义了与User具有一对一关系的模型的通用接口

    子类默认应当设置一对一字段名和展示字段名，或者覆盖模型和管理器的相应方法
    '''
    class Meta:
        abstract = True

    _USER_FIELD: str = NotImplemented
    _DISPLAY_FIELD: str = NotImplemented

    def __str__(self):
        return str(self.get_display_name())

    @staticmethod
    def get_type() -> str:
        '''
        获取模型的用户类型表示

        :return: 用户类型
        :rtype: str
        '''
        return ''

    def is_type(self, utype: str) -> bool:
        '''
        判断用户类型

        :param utype: 用户类型
        :type utype: str
        :return: 类型是否匹配
        :rtype: bool
        '''
        return self.get_type() == utype

    def get_user(self) -> User:
        '''
        获取对应的用户

        :return: 当前对象关联的User对象
        :rtype: User
        '''
        return getattr(self, self._USER_FIELD)

    def get_display_name(self) -> str:
        '''
        获取展示名称

        :return: 当前对象的名称
        :rtype: str
        '''
        return getattr(self, self._DISPLAY_FIELD)

    def get_absolute_url(self, absolute=False) -> str:
        '''
        获取主页网址

        :param absolute: 是否返回绝对地址, defaults to False
        :type absolute: bool, optional
        :return: 主页的网址
        :rtype: str
        '''
        return '/'

    def get_user_ava(self: Self | None = None) -> str:
        '''
        获取头像路径

        :return: 头像路径或默认头像
        :rtype: str
        '''
        return image_url('avatar/person_default.jpg')


class ClassifiedUserManager(models.Manager[ClassifiedUser]):
    '''
    已分类的用户模型管理器，定义了与User具有一对一关系的模型管理器的通用接口

    支持通过关联用户获取对象，以及筛选满足条件的对象集合
    '''

    def to_queryset(self, *,
                    update=False, activate=False) -> QuerySet[ClassifiedUser]:
        '''
        将管理器转化为筛选过的QuerySet

        :param update: 加锁, defaults to False
        :type update: bool, optional
        :param activate: 只筛选有效对象, defaults to False
        :type activate: bool, optional
        :return: 筛选后的集合
        :rtype: QuerySet[ClassifiedUser]
        '''
        if activate:
            self = self.activated()
        if update:
            self = self.select_for_update()
        return self.all()

    def get_by_user(self, user: User, *,
                    update=False, activate=False) -> ClassifiedUser:
        '''
        通过关联的User获取实例，仅管理ClassifiedUser子类时正确

        :param update: 加锁, defaults to False
        :type update: bool, optional
        :param activate: 只选择有效对象, defaults to False
        :type activate: bool, optional
        :raises: ClassifiedUser.DoesNotExist
        :return: 关联的实例
        :rtype: ClassifiedUser
        '''
        select_range = self.to_queryset(update=update, activate=activate)
        return select_range.get(**{self.model._USER_FIELD: user})

    def activated(self) -> QuerySet[ClassifiedUser]:
        '''筛选有效的对象'''
        return self.all()


class NaturalPersonManager(models.Manager['NaturalPerson']):
    def get_by_user(self, user: User, *,
                    update=False, activate=False):
        '''User一对一模型管理器的必要方法, 通过关联的User获取实例'''
        if activate:
            self = self.activated()
        if update:
            self = self.select_for_update()
        result: NaturalPerson = self.get(SQ.sq(NaturalPerson.person_id, user))
        return result

    def create(self, user: User, **kwargs) -> 'NaturalPerson':
        kwargs[SQ.f(NaturalPerson.person_id)] = user
        return super().create(**kwargs)

    def activated(self):
        return self.exclude(status=NaturalPerson.GraduateStatus.GRADUATED)

    def teachers(self, activate=True):
        if activate:
            self = self.activated()
        return self.filter(identity=NaturalPerson.Identity.TEACHER)

    def get_teachers(self, identifiers: list[str], activate: bool = True
                     ) -> QuerySet['NaturalPerson']:
        '''姓名或工号获取教师'''
        teachers = self.teachers(activate=activate)
        name_query = SQ.mq(NaturalPerson.name, IN=identifiers)
        uid_query = SQ.mq(NaturalPerson.person_id, User.username, IN=identifiers)
        return teachers.filter(name_query | uid_query)

    def get_teacher(self, name_or_id: str, activate: bool = True):
        '''姓名或工号，不存在或不止一个时抛出异常'''
        return self.get_teachers([name_or_id], activate=activate).get()


class NaturalPerson(models.Model):
    class Meta:
        verbose_name = "0.自然人"
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
    inform_share = models.BooleanField(default=True)  # 是否第一次展示有关分享的帮助
    last_time_login = models.DateTimeField("上次登录时间", blank=True, null=True)
    objects: NaturalPersonManager = NaturalPersonManager()
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)
    visit_times = models.IntegerField("浏览次数", default=0)  # 浏览主页的次数

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

    status = models.SmallIntegerField(
        "在校状态", choices=GraduateStatus.choices, default=0)

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
        MORE = (0, '接收全部消息')
        LESS = (500, '仅重要通知')
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

    def get_type(self=None) -> str:
        '''User一对一模型的必要方法'''
        return User.Type.PERSON.value

    def get_user(self) -> User:
        '''User一对一模型的必要方法'''
        return self.person_id

    def get_display_name(self) -> str:
        '''User一对一模型的必要方法'''
        return self.name

    def get_absolute_url(self, absolute=False):
        '''User一对一模型的建议方法'''
        url = f'/stuinfo/?name={self.name}'
        url += f'+{self.person_id_id}'
        return url

    def get_user_ava(self: Self | None = None):
        '''User一对一模型的建议方法，不存在时返回默认头像'''
        avatar = self.avatar if self is not None else ""
        if not avatar:
            avatar = "avatar/person_default.jpg"
        return image_url(avatar)

    def is_teacher(self, activate=True):
        result = self.identity == NaturalPerson.Identity.TEACHER
        if activate:
            result &= self.status != NaturalPerson.GraduateStatus.GRADUATED
        return result

    def get_accept_promote_display(self):
        return "是" if self.accept_promote else "否"

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

        # info += [self.stu_grade, self.stu_class]
        # info.append(self.nickname if (self.show_nickname) else unpublished)
        # info.append(
        #    unpublished if ((not self.show_gender) or (self.gender == None)) else gender[self.gender])
        # info.append(self.stu_major if (self.show_major) else "未公开")
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
        super().save(*args, **kwargs)


Person: TypeAlias = NaturalPerson


class OrganizationType(models.Model):
    class Meta:
        verbose_name = "1.小组类型"
        verbose_name_plural = verbose_name
        ordering = ["otype_name"]

    otype_id = models.SmallIntegerField(
        "小组类型编号", unique=True, primary_key=True)
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

    control_pos_threshold = models.SmallIntegerField("管理者权限等级上限", default=0)

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

    def default_semester(self):
        '''供生成时方便调用的函数，职位的默认持续时间'''
        return (GLOBAL_CONFIG.semester
                if self.otype_name == CONFIG.course.type_name
                else Semester.ANNUAL)

    def default_is_admin(self, position):
        '''供生成时方便调用的函数，是否成为负责人的默认值'''
        return position <= self.control_pos_threshold


class OrganizationTag(models.Model):
    class Meta:
        verbose_name = "1.组织类型标签"
        verbose_name_plural = verbose_name

    class ColorChoice(models.TextChoices):
        grey = ("#C1C1C1", "灰色")
        red = ("#DC143C", "红色")
        orange = ("#FFA500", "橙色")
        yellow = ("#FFD700", "黄色")
        green = ("#3CB371", "绿色")
        blue = ("#1E90FF", "蓝色")
        purple = ("#800080", "紫色")
        pink = ("#FF69B4", "粉色")
        brown = ("#DAA520", "棕色")
        coffee = ("#8B4513", "咖啡色")

    name = models.CharField("标签名", max_length=10, blank=False)
    color = models.CharField("颜色", choices=ColorChoice.choices, max_length=10)

    def __str__(self):
        return self.name


class OrganizationManager(models.Manager['Organization']):
    def get_by_user(self, user: User, *,
                    update=False, activate=False):
        '''User一对一模型管理器的必要方法, 通过关联的User获取实例'''
        if activate:
            self = self.activated()
        if update:
            self = self.select_for_update()
        result: Organization = self.get(organization_id=user)
        return result

    def activated(self):
        return self.exclude(status=False)


class Organization(models.Model):
    class Meta:
        verbose_name = "0.小组"
        verbose_name_plural = verbose_name

    organization_id = models.OneToOneField(User, on_delete=models.CASCADE)
    oname = models.CharField(max_length=32, unique=True)
    otype = models.ForeignKey(OrganizationType, on_delete=models.CASCADE)
    status = models.BooleanField("激活状态", default=True)  # 表示一个小组是否上线(或者是已经被下线)

    objects: OrganizationManager = OrganizationManager()

    introduction = models.TextField(
        "介绍", null=True, blank=True, default="这里暂时没有介绍哦~")
    avatar = models.ImageField(upload_to=f"avatar/", blank=True)
    QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)  # 二维码字段
    wallpaper = models.ImageField(upload_to=f"wallpaper/", blank=True)
    visit_times = models.IntegerField("浏览次数", default=0)  # 浏览主页的次数

    inform_share = models.BooleanField(default=True)  # 是否第一次展示有关分享的帮助

    # 组织类型标签，一个组织可能同时有多个标签
    tags = models.ManyToManyField(OrganizationTag)

    def __str__(self):
        return str(self.oname)

    def get_type(self=None) -> str:
        '''User一对一模型的必要方法'''
        return UTYPE_ORG

    def get_user(self) -> User:
        '''User一对一模型的必要方法'''
        return self.organization_id

    def get_display_name(self) -> str:
        '''User一对一模型的必要方法'''
        return self.oname

    def get_absolute_url(self, absolute=False):
        '''User一对一模型的建议方法'''
        url = f'/orginfo/?name={self.oname}'
        return url

    def get_user_ava(self: Self | None = None):
        '''User一对一模型的建议方法，不存在时返回默认头像'''
        avatar = self.avatar if self is not None else ""
        if not avatar:
            avatar = "avatar/org_default.png"
        return image_url(avatar)

    def get_subscriber_num(self, activated=True):
        '''仅供前端使用'''
        if activated:
            return NaturalPerson.objects.activated().exclude(
                id__in=self.unsubscribers.all()).count()
        return NaturalPerson.objects.all().count() - self.unsubscribers.count()


class PositionManager(models.Manager['Position']):
    def current(self):
        return select_current(self, 'year', 'semester')

    def noncurrent(self):
        return select_current(self, 'year', 'semester', noncurrent=True)

    def activated(self, noncurrent=False):
        return select_current(
            self.filter(status=Position.Status.INSERVICE),
            'year', 'semester',
            noncurrent=noncurrent)

    def create_application(self, person, org, apply_type, apply_pos):
        raise NotImplementedError('该函数已废弃')
        warn_duplicate_message = "There has already been an application of this state!"
        with transaction.atomic():
            if apply_type == "JOIN":
                apply_type = Position.ApplyType.JOIN
                assert len(self.activated().filter(
                    person=person, org=org)) == 0
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
        - year: 学年
        - semester: 学期
    成员变动申请相关：
        - apply_type: 申请类型
        - apply_status: 申请状态
        - apply_pos: 申请职务等级
    """

    class Meta:
        verbose_name = "1.职务"
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
    is_admin = models.BooleanField("是否是负责人", default=False)

    # 是否选择公开当前的职务
    show_post = models.BooleanField(default=True)

    # 表示是这个小组哪一年、哪个学期的成员
    year = models.IntegerField("当前学年", default=current_year)
    semester = models.CharField(
        "当前学期", choices=Semester.choices, default=Semester.ANNUAL, max_length=15
    )

    class Status(models.TextChoices):  # 职务状态
        INSERVICE = "在职"
        DEPART = "离职"
        # NONE = "无职务状态"  # 用于第一次加入小组申请

    status = models.CharField(
        "职务状态", choices=Status.choices, max_length=32, default=Status.INSERVICE
    )

    objects: PositionManager = PositionManager()

    def get_pos_number(self):  # 返回对应的pos number 并作超出处理
        return min(len(self.org.otype.job_name_list), self.pos)


# class ActivityManager(models.Manager['Activity']):
#     def activated(self, only_displayable=True, noncurrent=False):
#         # 选择学年相同，并且学期相同或者覆盖的
#         # 请保证query_range是一个queryset，将manager的行为包装在query_range计算完之前
#         if only_displayable:
#             query_range = self.displayable()
#         else:
#             query_range = self.all()
#         return select_current(query_range, noncurrent=noncurrent)

#     def displayable(self):
#         # REVIEWING, ABORT 状态的活动，只对创建者和审批者可见，对其他人不可见
#         # 过审后被取消的活动，还是可能被看到，也应该让学生看到这个活动被取消了
#         return self.exclude(status__in=[
#             Activity.Status.REVIEWING,
#             # Activity.Status.CANCELED,
#             Activity.Status.ABORT,
#             Activity.Status.REJECT
#         ])

#     def get_newlyended_activity(self):
#         # 一周内结束的活动
#         nowtime = datetime.now()
#         mintime = nowtime - timedelta(days=7)
#         return select_current(
#             self.filter(end__gt=mintime, status=Activity.Status.END))

#     def get_recent_activity(self):
#         # 开始时间在前后一周内，除了取消和审核中的活动。按时间逆序排序
#         nowtime = datetime.now()
#         mintime = nowtime - timedelta(days=7)
#         maxtime = nowtime + timedelta(days=7)
#         return select_current(self.filter(
#             start__gt=mintime,
#             start__lt=maxtime,
#             status__in=[
#                 Activity.Status.APPLYING,
#                 Activity.Status.WAITING,
#                 Activity.Status.PROGRESSING,
#                 Activity.Status.END
#             ],
#         )).order_by("category", "-start")

#     def get_newlyreleased_activity(self):
#         nowtime = datetime.now()
#         return select_current(self.filter(
#             publish_time__gt=nowtime - timedelta(days=7),
#             status__in=[
#                 Activity.Status.APPLYING,
#                 Activity.Status.WAITING,
#                 Activity.Status.PROGRESSING
#             ],
#         )).order_by("category", "-publish_time")

#     def get_today_activity(self):
#         # 开始时间在今天的活动,且不展示结束的活动。按开始时间由近到远排序
#         nowtime = datetime.now()
#         return self.filter(
#             status__in=[
#                 Activity.Status.APPLYING,
#                 Activity.Status.WAITING,
#                 Activity.Status.PROGRESSING,
#             ]
#         ).filter(start__date=nowtime.date(),
#                  ).order_by("start")


class CommentBase(models.Model):
    '''
    带有评论的模型基类

    模型性质
    -------
    - 可被评论
        - comment类依赖的外键
    - 聚合页面呈现模板
        - 默认呈现内容
         1. 实例名称(模型名<id>, 可通过定义__str__方法重载)
         2. 创建时间
         3. 上次修改时间
        - 显示创建者
            - 需定义`get_poster_name`方法
        - 呈现模板参考各类show.html
    - 审核评论页面模板
        - 显示状态
            - 需定义枚举字段status或`get_status_display`方法
            - 默认以返回的中文字符串决定呈现效果
             1. 包含“未/不/拒绝”的表示失败
             2. 此外包含“通过/接受”的表示审核通过
             3. 包含“修改”的为需要修改（可能用不到）
             4. 包含“取消”的为自己取消
             5. 其他都默认呈现“审核中”
        - 呈现模板参考各类modify.html

    继承要求
    -----------
    - 重载`save`方法
        - typename保存为类名的小写版本或类名，如`commentbase`
        - 在更新模型或对象时，应该调用save方法，从而更新修改时间等信息
    - 定义状态(可选)
        - `status`枚举字段，或`get_status_display`方法
        - 如不重载呈现模板，枚举字段的标签应为中文，或`get_status_display`返回中文
    - 定义创建者信息(可选)
        - `get_poster_name`方法，在审核页面呈现
        - 返回字符串
    - 显示更多信息(可选)
        - 定义`extra_display`方法
            - 返回一个二或三元组构成的列表
            - 每个元素是(键, 值, 图标名="envelope-o")
        - 呈现
            - 在审核页面呈现，发布者信息、修改时间之上，其他预定义信息之下
            - (键, 值, 图标名)将被渲染为一行 [图标]键：值
            - 图标名请参考fontawesome的图标类名

    @Author pht
    @Date 2022-03-11
    '''
    class Meta:
        verbose_name = "2.带有评论"
        verbose_name_plural = verbose_name

    id = models.AutoField(primary_key=True)  # 自增ID，标识唯一的基类信息
    typename = models.CharField(
        "模型类型", max_length=32, default="commentbase")   # 子类信息
    time = models.DateTimeField("发起时间", auto_now_add=True)
    modify_time = models.DateTimeField("上次修改时间", auto_now=True)  # 每次评论自动更新

    def get_instance(self):
        if self.typename.lower() == 'commentbase':
            return self
        try:
            return getattr(self, self.typename.lower())
        except:
            return self


# class Activity(CommentBase):
#     class Meta:
#         verbose_name = "3.活动"
#         verbose_name_plural = verbose_name

#     """
#     Jul 30晚, Activity类经历了较大的更新, 请阅读群里[活动发起逻辑]文档，看一下活动发起需要用到的变量
#     (1) 删除是否允许改变价格, 直接允许价格变动, 取消政策见文档【不允许投点的价格变动】
#     (2) 取消活动报名时间的填写, 改为选择在活动结束前多久结束报名，选项见EndBefore
#     (3) 活动容量[capacity]允许是正无穷
#     (4) 增加活动状态类, 恢复之前的活动状态记录方式, 通过定时任务来改变 #TODO
#     (5) 除了定价方式[bidding]之外的量都可以改变, 其中[capicity]不能低于目前已经报名人数, 活动的开始时间不能早于当前时间+1h
#     (6) 修改活动时间同步导致报名时间的修改, 当然也需要考虑EndBefore的修改; 这部分修改通过定时任务的时间体现, 详情请见地下室schedule任务的新建和取消
#     (7) 增加活动立项的接口, activated, 筛选出这个学期的活动(见class [ActivityManager])
#     """

#     title = models.CharField("活动名称", max_length=50)
#     organization_id = models.ForeignKey(
#         Organization,
#         on_delete=models.CASCADE,
#     )

#     year = models.IntegerField("活动年份", default=current_year)

#     semester = models.CharField(
#         "活动学期",
#         choices=Semester.choices,
#         max_length=15,
#         default=current_semester,
#     )

#     class PublishDay(models.IntegerChoices):
#         instant = (0, "立即发布")
#         oneday = (1, "提前一天")
#         twoday = (2, "提前两天")
#         threeday = (3, "提前三天")

#     publish_day = models.SmallIntegerField(
#         "信息发布提前时间", default=PublishDay.threeday)  # 默认为提前三天时间
#     publish_time = models.DateTimeField(
#         "信息发布时间", default=datetime.now)  # 默认为当前时间，可以被覆盖
#     need_apply = models.BooleanField("是否需要报名", default=False)

#     # 删除显示报名时间, 保留一个字段表示报名截止于活动开始前多久：1h / 1d / 3d / 7d
#     class EndBefore(models.IntegerChoices):
#         onehour = (0, "一小时")
#         oneday = (1, "一天")
#         threeday = (2, "三天")
#         oneweek = (3, "一周")

#     class EndBeforeHours:
#         prepare_times = [1, 24, 72, 168]

#     # TODO: 修改默认报名截止时间为活动开始前（5分钟）
#     endbefore = models.SmallIntegerField(
#         "报名截止于", choices=EndBefore.choices, default=EndBefore.oneday
#     )

#     apply_end = models.DateTimeField(
#         "报名截止时间", blank=True, default=datetime.now)
#     start = models.DateTimeField("活动开始时间", blank=True, default=datetime.now)
#     end = models.DateTimeField("活动结束时间", blank=True, default=datetime.now)
#     # prepare_time = models.FloatField("活动准备小时数", default=24.0)
#     # apply_start = models.DateTimeField("报名开始时间", blank=True, default=datetime.now)

#     location = models.CharField("活动地点", blank=True, max_length=200)
#     introduction = models.TextField("活动简介", max_length=225, blank=True)

#     QRcode = models.ImageField(upload_to=f"QRcode/", blank=True)  # 二维码字段

#     # url,活动二维码

#     bidding = models.BooleanField("是否投点竞价", default=False)

#     need_checkin = models.BooleanField("是否需要签到", default=False)

#     visit_times = models.IntegerField("浏览次数", default=0)

#     examine_teacher = models.ForeignKey(
#         NaturalPerson, on_delete=models.CASCADE, verbose_name="审核老师")
#     # recorded 其实是冗余，但用着方便，存了吧,activity_show.html用到了
#     recorded = models.BooleanField("是否预报备", default=False)
#     valid = models.BooleanField("是否已审核", default=False)

#     inner = models.BooleanField("内部活动", default=False)

#     # 允许是正无穷, 可以考虑用INTINF
#     capacity = models.IntegerField("活动最大参与人数", default=100)
#     current_participants = models.IntegerField("活动当前报名人数", default=0)

#     URL = models.URLField("活动相关(推送)网址", max_length=1024,
#                           default="", blank=True)

#     def __str__(self):
#         return str(self.title)

#     class Status(models.TextChoices):
#         REVIEWING = "审核中"
#         ABORT = "已撤销"
#         REJECT = "未过审"
#         CANCELED = "已取消"
#         APPLYING = "报名中"
#         UNPUBLISHED = "待发布"
#         WAITING = "等待中"
#         PROGRESSING = "进行中"
#         END = "已结束"

#     # 恢复活动状态的类别
#     status = models.CharField(
#         "活动状态", choices=Status.choices, default=Status.REVIEWING, max_length=32
#     )

#     objects: ActivityManager = ActivityManager()

#     class ActivityCategory(models.IntegerChoices):
#         NORMAL = (0, "普通活动")
#         COURSE = (1, "课程活动")

#     category = models.SmallIntegerField(
#         "活动类别", choices=ActivityCategory.choices, default=0
#     )

#     def save(self, *args, **kwargs):
#         self.typename = "activity"
#         super().save(*args, **kwargs)

#     def related_job_ids(self):
#         jobids = []
#         try:
#             jobids.append(f'activity_{self.id}_remind')
#             jobids.append(f'activity_{self.id}_{Activity.Status.APPLYING}')
#             jobids.append(f'activity_{self.id}_{Activity.Status.WAITING}')
#             jobids.append(f'activity_{self.id}_{Activity.Status.PROGRESSING}')
#             jobids.append(f'activity_{self.id}_{Activity.Status.END}')
#         except:
#             pass
#         return jobids

#     def popular_level(self, any_status=False):
#         if not any_status and not self.status in [
#             Activity.Status.WAITING,
#             Activity.Status.PROGRESSING,
#             Activity.Status.END,
#         ]:
#             return 0
#         if self.current_participants >= self.capacity:
#             return 2
#         if (self.current_participants >= 30
#             or (self.capacity >= 10 and self.current_participants >= self.capacity * 0.85)
#             ):
#             return 1
#         return 0

#     def has_tag(self):
#         if self.need_checkin or self.inner:
#             return True
#         if self.status == Activity.Status.APPLYING:
#             return True
#         if self.popular_level():
#             return True
#         return False

#     def eval_point(self) -> int:
#         '''计算价值的活动积分'''
#         # TODO: 添加到模型字段，固定每个活动的积分
#         hours = (self.end - self.start).seconds / 3600
#         if hours > CONFIG.yqpoint.activity.invalid_hour:
#             return 0
#         point = ceil(CONFIG.yqpoint.activity.per_hour * hours)
#         # 单次活动记录的积分上限，默认无上限
#         if CONFIG.yqpoint.activity.max is not None:
#             point = min(CONFIG.yqpoint.activity.max, point)
#         return point

#     @transaction.atomic
#     def settle_yqpoint(self, status: Status | None = None, point: int | None = None):
#         '''结算活动积分，应仅在活动结束时调用'''
#         if status is None:
#             status = self.status  # type: ignore
#         assert status == Activity.Status.END, "活动未结束，不能结算积分"
#         if point is None:
#             point = self.eval_point()
#         assert point >= 0, "活动积分不能为负"
#         # 活动积分为0时，不记录
#         if point == 0:
#             return

#         self = Activity.objects.select_for_update().get(pk=self.pk)
#         participation = SQ.sfilter(Participation.activity, self).filter(
#             status=Participation.AttendStatus.ATTENDED)
#         participant_ids = SQ.qsvlist(participation,
#                                      Participation.person, NaturalPerson.person_id)
#         participants = User.objects.filter(id__in=participant_ids)
#         User.objects.bulk_increase_YQPoint(
#             participants, point, "参加活动", YQPointRecord.SourceType.ACTIVITY)


# class ActivityPhoto(models.Model):
#     class Meta:
#         verbose_name = "3.活动图片"
#         verbose_name_plural = verbose_name
#         ordering = ["-time"]

#     class PhotoType(models.IntegerChoices):
#         ANNOUNCE = (0, "预告图片")
#         SUMMARY = (1, "总结图片")

#     type = models.SmallIntegerField(choices=PhotoType.choices)
#     image = models.ImageField(
#         upload_to=f"activity/photo/%Y/%m/", verbose_name=u'活动图片', null=True, blank=True)
#     activity = models.ForeignKey(
#         Activity, related_name="photos", on_delete=models.CASCADE)
#     activity_id: int
#     time = models.DateTimeField("上传时间", auto_now_add=True)

#     def get_image_path(self):
#         return image_url(self.image, enable_abs=True)


# class ParticipationManager(models.Manager['Participation']):
#     def activated(self, no_unattend=False):
#         '''返回成功报名的参与信息'''
#         exclude_status = [
#             Participation.AttendStatus.CANCELED,
#             Participation.AttendStatus.APPLYFAILED,
#         ]
#         if no_unattend:
#             exclude_status.append(Participation.AttendStatus.UNATTENDED)
#         return self.exclude(status__in=exclude_status)


# class Participation(models.Model):
#     class Meta:
#         verbose_name = "3.活动参与情况"
#         verbose_name_plural = verbose_name
#         ordering = ["activity_id"]

#     activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='+')
#     person = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE, related_name='+')

#     @necessary_for_frontend(person)
#     def get_participant(self):
#         '''供前端使用，追踪该字段的函数'''
#         return self.person

#     class AttendStatus(models.TextChoices):
#         APPLYING = "申请中"
#         APPLYFAILED = "活动申请失败"
#         APPLYSUCCESS = "已报名"
#         ATTENDED = "已参与"
#         UNATTENDED = "未签到"
#         CANCELED = "放弃"

#     status = models.CharField(
#         "学生参与活动状态",
#         choices=AttendStatus.choices,
#         default=AttendStatus.APPLYING,
#         max_length=32,
#     )
#     objects: ParticipationManager = ParticipationManager()


class NotificationManager(models.Manager['Notification']):
    def activated(self):
        return self.exclude(status=Notification.Status.DELETE)


class Notification(models.Model):
    class Meta:
        verbose_name = "o.通知消息"
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
        ACTIVITY_INFORM = "活动状态通知"
        VERIFY_INFORM = "审核信息通知"
        POSITION_INFORM = "成员变动通知"
        TRANSFER_FEEDBACK = "转账回执"
        NEW_ORGANIZATION = "新建小组通知"
        PENDING_INFORM = "事务开始通知"
        FEEDBACK_INFORM = "反馈通知"

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
    relate_instance = models.ForeignKey(
        CommentBase,
        related_name="relate_notifications",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    objects: NotificationManager = NotificationManager()

    def get_title_display(self):
        return str(self.title)


class Comment(models.Model):
    class Meta:
        verbose_name = "2.评论"
        verbose_name_plural = verbose_name
        ordering = ["-time"]

    commentator = models.ForeignKey(
        User, on_delete=models.CASCADE, verbose_name="评论者")
    commentbase = models.ForeignKey(
        CommentBase, related_name="comments", on_delete=models.CASCADE
    )
    text = models.TextField("文字内容", default="", blank=True)
    time = models.DateTimeField("评论时间", auto_now_add=True)


class CommentPhoto(models.Model):
    class Meta:
        verbose_name = "2.评论图片"
        verbose_name_plural = verbose_name

    image = models.ImageField(
        upload_to=f"comment/%Y/%m/", verbose_name="评论图片", null=True, blank=True
    )
    comment = models.ForeignKey(
        Comment, related_name="comment_photos", on_delete=models.CASCADE
    )

    # 路径无法加上相应图片
    def get_image_path(self):
        return image_url(self.image)


class ModifyOrganization(CommentBase):
    class Meta:
        verbose_name = "1.新建小组"
        verbose_name_plural = verbose_name
        ordering = ["-modify_time", "-time"]

    oname = models.CharField(max_length=32)  # 这里不设置unique的原因是可能是已取消
    otype = models.ForeignKey(OrganizationType, on_delete=models.CASCADE)
    introduction = models.TextField(
        "介绍", null=True, blank=True, default="这里暂时没有介绍哦~")
    application = models.TextField(
        "申请理由", null=True, blank=True, default="这里暂时还没写申请理由哦~"
    )
    avatar = models.ImageField(
        upload_to=f"avatar/", verbose_name="小组头像", default="avatar/org_default.png", null=True, blank=True
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
            return NaturalPerson.objects.get_by_user(self.pos).name
        except:
            return '未知'

    def extra_display(self):
        display = []
        if self.introduction and self.introduction != '这里暂时没有介绍哦~':
            display.append(('小组介绍', self.introduction))
        return display

    def get_user_ava(self):
        avatar = self.avatar
        if not avatar:
            avatar = Organization.get_user_ava()
        return image_url(avatar)

    def is_pending(self):  # 表示是不是pending状态
        return self.status == ModifyOrganization.Status.PENDING


class ModifyPosition(CommentBase):
    class Meta:
        verbose_name = "1.成员申请详情"
        verbose_name_plural = verbose_name
        ordering = ["-modify_time", "-time"]

    # 申请人
    person = models.ForeignKey(NaturalPerson, on_delete=models.CASCADE,
                               related_name="position_application")

    # 申请小组
    org = models.ForeignKey(Organization, on_delete=models.CASCADE,
                            related_name="position_application")

    # 申请职务等级
    pos = models.SmallIntegerField(
        verbose_name="申请职务等级", blank=True, null=True)

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

    def is_pending(self):  # 表示是不是pending状态
        return self.status == ModifyPosition.Status.PENDING

    def accept_submit(self):  # 同意申请，假设都是合法操作
        if self.apply_type == ModifyPosition.ApplyType.WITHDRAW:
            Position.objects.activated().filter(
                org=self.org, person=self.person
            ).update(status=Position.Status.DEPART)
        elif self.apply_type == ModifyPosition.ApplyType.JOIN:
            # 尝试获取已有的position
            current_positions = Position.objects.current().filter(
                org=self.org, person=self.person)
            if current_positions.exists():  # 如果已经存在这个量了
                current_positions.update(
                    pos=self.pos,
                    is_admin=self.org.otype.default_is_admin(self.pos),
                    semester=self.org.otype.default_semester(),
                    status=Position.Status.INSERVICE,
                )
            else:  # 不存在 直接新建
                Position.objects.create(
                    pos=self.pos,
                    person=self.person,
                    org=self.org,
                    is_admin=self.org.otype.default_is_admin(self.pos),
                    semester=self.org.otype.default_semester(),
                )
        else:   # 修改 则必定存在这个量
            Position.objects.activated().filter(
                org=self.org, person=self.person).update(
                    pos=self.pos, is_admin=self.org.otype.default_is_admin(self.pos))
        # 修改申请状态
        ModifyPosition.objects.filter(id=self.id).update(
            status=ModifyPosition.Status.CONFIRMED)

    def save(self, *args, **kwargs):
        self.typename = "modifyposition"
        super().save(*args, **kwargs)


class Help(models.Model):
    '''
        页面帮助类
    '''
    title = models.CharField("帮助标题", max_length=20, blank=False)
    content = models.TextField("帮助内容", max_length=500)

    class Meta:
        verbose_name = "~A.页面帮助"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.title


class Wishes(models.Model):
    class Meta:
        verbose_name = "~A.心愿"
        verbose_name_plural = verbose_name
        ordering = ["-time"]

    COLORS = [
        "#FDAFAB", "#FFDAC1", "#FAF1D6",
        "#B6E3E9", "#B5EAD7", "#E2F0CB",
    ]

    # 不要随便删 admin.py也依赖本随机函数，3.10可以直接调用static方法
    def rand_color():  # type: ignore
        return random.choice(Wishes.COLORS)

    text = models.TextField("心愿内容", default="", blank=True)
    time = models.DateTimeField("发布时间", auto_now_add=True)
    background = models.TextField("颜色编码", default=rand_color)


class ModifyRecord(models.Model):
    # 仅用作记录，之后大概会删除吧，所以条件都设得很宽松
    class Meta:
        verbose_name = "~R.修改记录"
        verbose_name_plural = verbose_name
        ordering = ["-time"]
    user = models.ForeignKey(User, on_delete=models.SET_NULL,
                                   related_name="modify_records",
                                   to_field='username', blank=True, null=True)
    usertype = models.CharField('用户类型', max_length=16, default='', blank=True)
    name = models.CharField('名称', max_length=32, default='', blank=True)
    info = models.TextField('相关信息', default='', blank=True)
    time = models.DateTimeField('修改时间', auto_now_add=True)


# class ActivitySummary(models.Model):
#     class Meta:
#         verbose_name = "3.活动总结"
#         verbose_name_plural = verbose_name
#         ordering = ["-time"]

#     class Status(models.IntegerChoices):
#         WAITING = (0, "待审核")
#         CONFIRMED = (1, "已通过")
#         CANCELED = (2, "已取消")
#         REFUSED = (3, "已拒绝")

#     activity = models.ForeignKey(Activity, on_delete=models.CASCADE)

#     status = models.SmallIntegerField(choices=Status.choices, default=0)
#     image = models.ImageField(upload_to=f"ActivitySummary/photo/%Y/%m/",
#                               verbose_name='活动总结图片', null=True, blank=True)
#     time = models.DateTimeField("申请时间", auto_now_add=True)

#     def __str__(self):
#         return f'{self.activity.title}活动总结'

#     def is_pending(self):  # 表示是不是pending状态
#         return self.status == ActivitySummary.Status.WAITING

#     @necessary_for_frontend('activity.organization_id')
#     def get_org(self):
#         return self.activity.organization_id

#     @necessary_for_frontend('activity.title', '__str__')
#     def get_audit_display(self):
#         return f'{self.activity.title}总结'
