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
import pypinyin
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as _UserManager
from django.db import transaction
from django.db.models import QuerySet

__all__ = [
    'User',
    'CreditRecord',
]


def necessary_for_frontend(method, *fields):
    '''前端必须使用此方法代替直接访问相关属性，如限制choice的属性，可以在参数中标记相关字段'''
    if isinstance(method, (str, models.Field)):
        return necessary_for_frontend
    return method

def invalid_for_frontend(method):
    '''前端不能使用这个方法'''
    return method


def to_acronym(name: str) -> str:
    '''生成缩写'''
    pinyin_list = pypinyin.pinyin(name, style=pypinyin.NORMAL)
    return ''.join([w[0][0] for w in pinyin_list])


class UserManager(_UserManager):
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

    def create(self, **fields):
        '''User.objects.create已废弃'''
        raise NotImplementedError

    def get(self, *args, **kwargs) -> 'User':
        return super().get(*args, **kwargs)

    def all(self) -> 'QuerySet[User]':
        return super().all()

    def filter(self, *args, **kwargs) -> 'QuerySet[User]':
        return super().filter(*args, **kwargs)


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


class PointMixin(models.Model):
    '''
    支持元气值和积分等系统，添加相关字段和操作

    元气值暂由修改者负责添加记录
    '''
    class Meta:
        abstract = True

    YQpoint = models.IntegerField('元气值', default=0)

    def _normalize_YQpoint(self):
        pass

    def changeYQpoint(self, value):
        self.YQpoint += value
        self._normalize_YQpoint()


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
        PERSON = 'Person', '自然人'
        ORG = 'Organization', '组织'
        SPECIAL = '', '特殊用户'

    name = models.CharField('名称', max_length=32)
    acronym = models.CharField('缩写', max_length=32, default='', blank=True)
    utype: 'str|Type' = models.CharField(
        '用户类型', max_length=20,
        choices=Type.choices,
        default='', blank=True,
    )

    REQUIRED_FIELDS = ['name']
    objects: UserManager = UserManager()

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
