'''
models.py

- 自定义用户模型
    - 任何应用模型如果有用户模型关系，都应该导入，并提供导出
    - 任何应用都应从其models文件导入User模型
- 用户管理器
    - 提供管理方法，并保存记录

注意事项
- 如果在使用本应用前已经迁移过，且想保留用户数据，请务必参考readme.md

@Author pht
@Date 2022-08-19
'''
from typing import Type, NoReturn, Final

from django.db import models
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import AbstractUser, AnonymousUser, Permission
from django.contrib.auth.models import UserManager as _UserManager
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet, F
import pypinyin

import utils.models.query as SQ
from utils.models.choice import choice
from utils.models.descriptor import necessary_for_frontend, invalid_for_frontend, admin_only

__all__ = [
    'User',
    'PermissionBlacklist',
    'CreditRecord',
    'YQPointRecord',
]


def get_pinyin(name: str) -> list[str]:
    '''转为拼音'''
    pinyin_list = pypinyin.pinyin(name, style=pypinyin.NORMAL)
    return [prons[0] for prons in pinyin_list]


def to_acronym(name: str) -> str:
    '''生成缩写'''
    return ''.join([pron[0] for pron in get_pinyin(name)])


class UserManager(_UserManager['User']):
    '''
    用户管理器，提供对信用分等通用字段的修改方法
    '''

    def get_user(self, user: 'User | int | str', update=False) -> 'User':
        '''根据主键或用户名(学号)等唯一字段查询对应的用户'''
        users = self.all()
        if update:
            users = users.select_for_update()
        if isinstance(user, User):
            user = user.pk
        if isinstance(user, str):
            return users.get(username=user)
        return users.get(pk=user)

    def filter_type(self, usertype: 'User.Type | str | list[User.Type]'):
        '''
        根据用户类型过滤用户

        Args:
        - type: 用户类型，可选值为`User.Type`枚举值、其对应的字符串和一组枚举值
        '''
        users = self.all()
        if usertype == User.Type.PERSON:
            usertype = User.Type.Persons()
        if isinstance(usertype, str | User.Type):
            users = users.filter(utype=usertype)
        else:
            users = users.filter(utype__in=usertype)
        return users

    def create_user(self, username: str, name: str,
                    usertype: 'User.Type | None' = None, *,
                    password: str | None = None,
                    **extra_fields) -> 'User':
        '''创建用户，根据名称自动设置名称缩写'''
        if usertype is not None:
            extra_fields['utype'] = usertype
        extra_fields['name'] = name
        extra_fields.setdefault('pinyin', ''.join(get_pinyin(name)))
        extra_fields.setdefault('acronym', to_acronym(name))
        return super().create_user(username=username, password=password, **extra_fields)

    def create_superuser(self, username: str, name: str,
                         usertype: 'User.Type | None' = None, *,
                         password: str | None = None,
                         **extra_fields) -> 'User':
        '''创建超级用户'''
        if usertype is None:
            usertype = extra_fields.pop('utype', User.Type.SPECIAL)
        extra_fields.update(utype=usertype, name=name)
        return super().create_superuser(username=username, password=password, **extra_fields)

    def create(self, **fields) -> 'NoReturn':
        '''User.objects.create已废弃'''
        raise NotImplementedError

    def check_perm(self, user: 'User | AnonymousUser',
                   model: 'Type[models.Model] | models.Model', perm: str) -> bool:
        '''
        检查当前用户在对应模型中是否具有对应权限

        :param user: 未经验证的用户
        :type user: User | AnonymousUser
        :param model: 待检查的模型或实例
        :type model: Type[Model] | Model
        :param perm: 权限名称，如change, view
        :type perm: str
        :return: 是否具有权限
        :rtype: bool
        '''
        opts = model._meta
        codename = get_permission_codename(perm, opts)
        perm_name = f'{opts.app_label}.{codename}'
        return user.has_perm(perm_name)

    @transaction.atomic
    def modify_credit(self, user: 'User | int | str', delta: int, source: str) -> int:
        '''
        修改信用分并记录，至多扣到0分，原子化操作

        :param user: 修改的用户，可以是对象、主键或用户名
        :type user: User | int | str
        :param delta: 希望的变化量，最终修改结果在MIN_CREDIT到MAX_CREDIT之间
        :type delta: int
        :param source: 修改来源，可以是“地下室”等应用名，尽量简单
        :type source: str
        :return: 实际信用分修改量
        :rtype: int
        '''
        update_user = self.get_user(user, update=True)
        old_credit = update_user.credit
        new_credit = old_credit + delta
        new_credit = max(new_credit, User.MIN_CREDIT)
        new_credit = min(new_credit, User.MAX_CREDIT)
        self._record_credit_modify(
            update_user, delta, source,
            old_value=old_credit, new_value=new_credit,
        )
        # 写完记录后修改
        update_user.credit = new_credit
        update_user.save(update_fields=['credit'])
        if isinstance(user, User):
            user.credit = update_user.credit
        return new_credit - old_credit

    @transaction.atomic
    def bulk_recover_credit(self, users: QuerySet['User'],
                            delta: int, source: str):
        '''
        批量恢复信用分并记录，原子化操作

        :param users: 修改的用户集合，**不修改**内部对象
        :type users: QuerySet[User]
        :param delta: 希望的变化量，至多恢复到MAX_CREDIT，超出不扣分
        :type delta: int
        :param source: 修改来源，可以是“地下室”等应用名，尽量简单
        :type source: str
        '''
        assert delta > 0, '恢复的信用分必须为正数'
        records = []
        users = users.select_for_update().all()
        for user in users:
            old_value = user.credit
            if user.credit > User.MAX_CREDIT:
                user.credit = old_value
            else:
                user.credit = min(old_value + delta, User.MAX_CREDIT)
            overflow = (user.credit != old_value + delta)
            records.append(
                CreditRecord(
                    user=user,
                    old_credit=old_value,
                    new_credit=user.credit,
                    delta=delta,
                    overflow=overflow,
                    source=source,
                ))
        CreditRecord.objects.bulk_create(records)
        self.select_for_update().bulk_update(users, ['credit'])

    def _record_credit_modify(self, user: 'User', delta: int, source: str,
                              old_value: int | None = None,
                              new_value: int | None = None):
        if old_value is None:
            old_value = user.credit
        if new_value is None:
            new_value = old_value + delta
        overflow = (new_value != old_value + delta)
        CreditRecord.objects.create(
            user=user,
            old_credit=old_value,
            new_credit=new_value,
            delta=delta,
            overflow=overflow,
            source=source,
        )

    @transaction.atomic
    def modify_YQPoint(self, user: 'User | int | str', delta: int,
                       source: str, source_type: 'YQPointRecord.SourceType'):
        '''
        修改元气值并记录，不足扣除时抛出AssertionError，原子化操作
        '''
        update_user = self.get_user(user, update=True)
        update_user.YQpoint += delta
        assert not (update_user.YQpoint < 0 and delta < 0), '元气值不足'
        self._record_YQpoint_change(update_user, delta, source, source_type)
        update_user.save(update_fields=['YQpoint'])
        if isinstance(user, User):
            user.YQpoint = update_user.YQpoint

    @transaction.atomic
    def _bulk_change_YQPoint(self, users: QuerySet['User'], delta: int,
                             source: str, source_type: 'YQPointRecord.SourceType'):
        '''
        无条件批量修改元气值并记录，不论元气值**是否足够**，原子化操作

        Warning:
            请勿直接调用，应使用`bulk_increase_YQPoint`或`bulk_withdraw_YQPoint`
            实验表明`users`不应该包含复杂的级联查询，如`id__in=xxx.values('id')`，
            否则可能由未知原因导致`OperationalError`
        '''
        users = users.select_for_update()
        point_records = [
            YQPointRecord(
                user=user,
                delta=delta,
                source=source,
                source_type=source_type,
            ) for user in users
        ]
        YQPointRecord.objects.bulk_create(point_records)
        if delta != 0:
            users.update(YQpoint=F('YQpoint') + delta)

    def bulk_increase_YQPoint(self, users: QuerySet['User'], delta: int,
                              source: str, source_type: 'YQPointRecord.SourceType'):
        '''
        批量增加元气值

        Args:
        - users(QuerySet[User]): 待更改的用户集合，不修改内部对象
        - delta(int): 增加的元气值数量，必须为非负数
        - source(str): 元气值来源的简短说明
        - source_type(YQPointRecord.SourceType): 元气值来源类型

        Raises:
            AssertionError: 元气值增量为负数
        '''
        assert delta >= 0, '元气值增量为负数'
        return self._bulk_change_YQPoint(users, delta, source, source_type)

    def bulk_withdraw_YQPoint(self, users: QuerySet['User'], value: int,
                              source: str, source_type: 'YQPointRecord.SourceType'):
        '''
        强制批量收回元气值，可能导致元气值为负数

        Args:
        - users(QuerySet[User]): 待更改的用户集合，不修改内部对象
        - value(int): 收回的元气值数量，必须为非负数
        - source(str): 元气值来源的简短说明
        - source_type(YQPointRecord.SourceType): 元气值来源类型

        Raises:
            AssertionError: 元气值收回量为负数

        Warning:
            只适合收回元气值，不适合用于扣除元气值，因为并不检查对象是否足够支付
        '''
        assert value >= 0, '元气值收回量为负数'
        return self._bulk_change_YQPoint(users, -value, source, source_type)

    def _record_YQpoint_change(self, user: 'User', delta: int,
                               source: str, source_type: 'YQPointRecord.SourceType'):
        YQPointRecord.objects.create(
            user=user,
            delta=delta,
            source=source,
            source_type=source_type,
        )


class PointMixin(models.Model):
    '''
    支持元气值和积分等系统，添加相关字段和操作

    元气值修改由管理器负责并添加记录
    '''
    class Meta:
        abstract = True

    YQpoint = models.IntegerField('元气值', default=0)


class UserBase(models.base.ModelBase):
    '''临时的类型提示助手'''
    @property
    def objects(cls) -> UserManager: ...
    del objects


class User(AbstractUser, PointMixin, metaclass=UserBase):
    '''用户模型

    Attributes:
    - id: 用户主键
    - username: 用户名，学号
    - name: 用户名称
    - utype: 用户类型，参考User.Type
    - 其它继承字段参考AbstractUser

    See Also:
    - :class:`UserManager`
    - :class:`django.contrib.auth.models.AbstractUser`
    '''

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        # db_table = 'auth_user'

    MIN_CREDIT: Final = 0
    MAX_CREDIT: Final = 3
    credit = models.IntegerField('信用分', default=MAX_CREDIT)

    # For student, means not graduated
    # For teacher, means not retired
    # For organization, means not dissolved
    # TODO: copy from NaturalPerson & Organization
    # 注意：不同于django的is_active
    active = models.BooleanField('激活状态', default=True)

    accept_chat = models.BooleanField('允许提问', default=True)
    accept_anonymous_chat = models.BooleanField('允许匿名提问', default=True)

    class Type(models.TextChoices):
        PERSON = choice('Person', '自然人')
        STUDENT = choice('Student', '学生')
        TEACHER = choice('Teacher', '老师')
        ORG = choice('Organization', '组织')
        UNAUTHORIZED = choice('Unauthorized', '未授权')
        SPECIAL = choice('', '特殊用户')

        @classmethod
        def Persons(cls) -> list['User.Type']:
            # TODO: 待后端都使用本接口判断后，修改类型判断
            return [cls.PERSON, cls.STUDENT, cls.TEACHER]

    name = models.CharField('名称', max_length=32)
    pinyin = models.CharField('拼音', max_length=100, default='', blank=True)
    acronym = models.CharField('缩写', max_length=32, default='', blank=True)
    utype: Type | str = models.CharField(
        '用户类型', max_length=20,
        choices=Type.choices,
        default='', blank=True,
    )  # type: ignore
    is_newuser = models.BooleanField('首次登录', default=True)

    REQUIRED_FIELDS = ['name']
    objects: UserManager = UserManager()

    @admin_only
    def __str__(self) -> str:
        return f'{self.username} ({self.name})'

    @necessary_for_frontend(name)
    def get_full_name(self) -> str:
        '''User的通用方法，展示用户的名称'''
        return self.name

    @necessary_for_frontend(acronym)
    def get_short_name(self) -> str:
        '''User的通用方法，展示用户的简写'''
        return self.acronym

    @invalid_for_frontend
    def is_valid(self) -> bool:
        '''返回用户是否合法，存在对应的子类对象'''
        # TODO: 需要接入访客时，重新设计
        return self.utype not in [self.Type.SPECIAL, self.Type.UNAUTHORIZED]

    @necessary_for_frontend(utype)
    def is_person(self) -> bool:
        return self.utype in self.Type.Persons()

    @necessary_for_frontend(utype)
    def is_student(self) -> bool:
        return self.utype == self.Type.STUDENT

    @necessary_for_frontend(utype)
    def is_teacher(self) -> bool:
        return self.utype == self.Type.TEACHER

    @necessary_for_frontend(utype)
    def is_org(self) -> bool:
        return self.utype == self.Type.ORG


class PermissionBlacklistManager(models.Manager['PermissionBlacklist']):
    '''
    权限黑名单管理器

    用于提供对权限黑名单的查询方法
    '''

    def get_revoked_permissions(self, user: User) -> set[str]:
        '''
        获取用户被禁止的权限

        Args:
            user (User): 要查询的对象

        Returns:
            set[str]: 被禁止的权限字符串集合
        '''
        _M = PermissionBlacklist
        perms = self.filter(SQ.sq(_M.user, user)).values_list(
            SQ.f(_M.permission, Permission.content_type, ContentType.app_label),
            SQ.f(_M.permission, Permission.codename)
        )
        return {f'{app_label}.{codename}' for app_label, codename in perms}


class PermissionBlacklist(models.Model):
    '''
    权限黑名单

    记录哪些用户被取消了哪些权限。在认证后端鉴权时，这个表中记录的信息比用户组优先级更高。
    '''
    class Meta:
        verbose_name = '权限黑名单'
        verbose_name_plural = verbose_name

    user = models.ForeignKey(
        User, verbose_name='用户', on_delete=models.CASCADE,
        to_field='username',
    )
    permission = models.ForeignKey(
        Permission, verbose_name='权限', on_delete=models.CASCADE,
    )

    objects: PermissionBlacklistManager = PermissionBlacklistManager()


class CreditRecord(models.Model):
    '''
    信用分更改记录

    只起记录作用，应通过User管理器方法自动创建
    '''
    class Meta:
        verbose_name = '信用分记录'
        verbose_name_plural = verbose_name

    user = models.ForeignKey(
        User, verbose_name='用户', on_delete=models.CASCADE,
        to_field='username',
    )
    old_credit = models.IntegerField('原信用分')
    new_credit = models.IntegerField('现信用分')
    delta = models.IntegerField('变化量')
    overflow = models.BooleanField('溢出', default=False)
    source = models.CharField('来源', max_length=50, default='', blank=True)
    time = models.DateTimeField('时间', auto_now_add=True)


class YQPointRecord(models.Model):
    '''
    元气值更改记录

    只起记录作用，应通过User管理器方法自动创建
    '''
    class Meta:
        verbose_name = '元气值记录'
        verbose_name_plural = verbose_name

    user = models.ForeignKey(
        User, verbose_name='用户', on_delete=models.CASCADE,
        to_field='username',
    )
    delta = models.IntegerField('变化量')
    source = models.CharField('来源', max_length=50, blank=True)

    # TODO: Can we remove this?
    class SourceType(models.IntegerChoices):
        SYSTEM = (0, '系统操作')
        CHECK_IN = (1, '每日签到')
        ACTIVITY = (2, '参与活动')
        FEEDBACK = (3, '问题反馈')
        # 如完成个人信息填写，学术地图填写
        ACHIEVE = (4, '达成成就')
        QUESTIONNAIRE = (5, '填写问卷')
        CONSUMPTION = (6, '奖池花费')
        COMPENSATION = (7, '奖池补偿')

    source_type = models.SmallIntegerField(
        '来源类型', choices=SourceType.choices, default=SourceType.SYSTEM)
    time = models.DateTimeField('时间', auto_now_add=True)
