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
from typing import Type, NoReturn
from datetime import datetime

from django.db import models
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import AbstractUser, AnonymousUser
from django.contrib.auth.models import UserManager as _UserManager
from django.db import transaction
from django.db.models import QuerySet, F
import pypinyin

__all__ = [
    'User',
    'CreditRecord',
    'YQPointRecord',
    'PageLog',
    'ModuleLog',
]


def necessary_for_frontend(method, *fields):
    '''前端必须使用此方法代替直接访问相关属性，如限制choice的属性，可以在参数中标记相关字段'''
    if isinstance(method, (str, models.Field)):
        return necessary_for_frontend
    return method


def invalid_for_frontend(method):
    '''前端不能使用这个方法'''
    return method


def debug_only(method):
    '''仅用于提供调试信息，如报错、后台、日志记录等，必须对用户不可见'''
    return method


def to_acronym(name: str) -> str:
    '''生成缩写'''
    pinyin_list = pypinyin.pinyin(name, style=pypinyin.NORMAL)
    return ''.join([w[0][0] for w in pinyin_list])


class UserManager(_UserManager['User']):
    '''
    用户管理器，提供对信用分等通用
    '''

    def get_user(self, user: 'User|int|str', update=False) -> 'User':
        '''根据主键或用户名(学号)等唯一字段查询对应的用户'''
        users = self.all()
        if update:
            users = users.select_for_update()
        if isinstance(user, User):
            user = user.pk
        if isinstance(user, str):
            return users.get(username=user)
        return users.get(pk=user)

    def create_user(self, username: str, name: str,
                    usertype: 'User.Type' = None, *,
                    password: str = None,
                    **extra_fields) -> 'User':
        '''创建用户，根据名称自动设置名称缩写'''
        if usertype is not None:
            extra_fields['utype'] = usertype
        extra_fields['name'] = name
        extra_fields.setdefault('acronym', to_acronym(name))
        return super().create_user(username=username, password=password, **extra_fields)

    def create(self, **fields) -> 'NoReturn':
        '''User.objects.create已废弃'''
        raise NotImplementedError

    def check_perm(self, user: 'User|AnonymousUser',
                   model: 'Type[models.Model]|models.Model', perm: str) -> bool:
        '''
        检查当前用户在对应模型中是否具有对应权限

        :param user: 未经验证的用户
        :type user: User|AnonymousUser
        :param model: 待检查的模型或实例
        :type model: Type[Model]|Model
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
    def modify_credit(self, user: 'User|int|str', delta: int, source: str) -> int:
        '''
        修改信用分并记录，至多扣到0分，原子化操作

        :param user: 修改的用户，可以是对象、主键或用户名
        :type user: User|int|str
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
                              old_value: int = None, new_value: int = None):
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
    def modify_YQPoint(self, user: 'User|int|str', delta: int,
                       source: str, source_type: 'YQPointRecord.SourceType'):
        '''
        修改元气值并记录，不足时抛出AssertionError，原子化操作
        '''
        update_user = self.get_user(user, update=True)
        update_user.YQpoint += delta
        assert update_user.YQpoint >= 0, '元气值不足'
        self._record_YQpoint_change(update_user, delta, source, source_type)
        update_user.save(update_fields=['YQpoint'])
        if isinstance(user, User):
            user.YQpoint = update_user.YQpoint

    @transaction.atomic
    def bulk_increase_YQPoint(self, users: QuerySet['User'], delta: int,
                              source: str, source_type: 'YQPointRecord.SourceType'):
        '''
        批量增加元气值
        :param users: 待更改User的QuerySet，不修改内部对象

        :type users: QuerySet['User']
        :param delta: 增加多少元气值
        :type delta: int
        :param source: 元气值来源的简短说明
        :type source: str
        :param source_type: 元气值来源类型
        :type source_type: YQPointRecord.SourceType
        '''
        assert delta >= 0, '元气值增量为负数'
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


class User(AbstractUser, PointMixin):

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        # db_table = 'auth_user'

    MIN_CREDIT = 0
    MAX_CREDIT = 3
    credit = models.IntegerField('信用分', default=MAX_CREDIT)

    accept_chat = models.BooleanField('允许提问', default=True)
    accept_anonymous_chat = models.BooleanField('允许匿名提问', default=True)

    class Type(models.TextChoices):
        PERSON = 'Person', '自然人' # Deprecated
        STUDENT = 'Student', '学生'
        TEACHER = 'Teacher', '老师'
        ORG = 'Organization', '组织'
        UNAUTHORIZED = 'Unauthorized', '未授权'
        SPECIAL = '', '特殊用户'

    name = models.CharField('名称', max_length=32)

    acronym = models.CharField('缩写', max_length=32, default='', blank=True)
    utype: 'str|Type' = models.CharField(
        '用户类型', max_length=20,
        choices=Type.choices,
        default='', blank=True,
    )
    first_time_login = models.BooleanField(default=True)

    REQUIRED_FIELDS = ['name']
    objects: UserManager = UserManager()

    @debug_only
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
        return self.utype != self.Type.SPECIAL

    @necessary_for_frontend(utype)
    def is_person(self) -> bool:
        return self.utype == self.Type.PERSON
        return self.is_student() or self.is_teacher()

    @necessary_for_frontend(utype)
    def is_student(self) -> bool:
        return self.utype == self.Type.STUDENT

    @necessary_for_frontend(utype)
    def is_teacher(self) -> bool:
        return self.utype == self.Type.TEACHER

    @necessary_for_frontend(utype)
    def is_org(self) -> bool:
        return self.utype == self.Type.ORG


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
    time = models.DateTimeField("时间", auto_now_add=True)


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

    source_type: 'SourceType|int' = models.SmallIntegerField(
        '来源类型', choices=SourceType.choices, default=SourceType.SYSTEM)
    time = models.DateTimeField("时间", auto_now_add=True)


class PageLog(models.Model):
    '''
    统计Page类埋点数据(PV/PD)
    '''
    class Meta:
        verbose_name = "~R.Page类埋点记录"
        verbose_name_plural = verbose_name

    class CountType(models.IntegerChoices):
        PV = 0, "Page View"
        PD = 1, "Page Disappear"

    user: User = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.IntegerField('事件类型', choices=CountType.choices)

    page = models.URLField('页面url', max_length=256, blank=True)
    time = models.DateTimeField('发生时间', default=datetime.now)
    platform = models.CharField('设备类型', max_length=32, null=True, blank=True)
    explore_name = models.CharField('浏览器类型', max_length=32, null=True, blank=True)
    explore_version = models.CharField('浏览器版本', max_length=32, null=True, blank=True)


class ModuleLog(models.Model):
    '''
    统计Module类埋点数据(MV/MC)
    '''
    class Meta:
        verbose_name = "~R.Module类埋点记录"
        verbose_name_plural = verbose_name

    class CountType(models.IntegerChoices):
        MV = 2, "Module View"
        MC = 3, "Module Click"

    user: User = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.IntegerField('事件类型', choices=CountType.choices)

    page = models.URLField('页面url', max_length=256, blank=True)
    module_name = models.CharField('模块名称', max_length=64, blank=True)
    time = models.DateTimeField('发生时间', default=datetime.now)
    platform = models.CharField('设备类型', max_length=32, null=True, blank=True)
    explore_name = models.CharField('浏览器类型', max_length=32, null=True, blank=True)
    explore_version = models.CharField('浏览器版本', max_length=32, null=True, blank=True)
