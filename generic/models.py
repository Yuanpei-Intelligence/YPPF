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
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as _UserManager
from django.db import transaction

__all__ = [
    'User',
]


class UserManager(_UserManager):
    '''
    用户管理器，提供对信用分等通用
    '''
    def get_user(self, user: 'User|int|str', update=False) -> 'User':
        users = self.all()
        if update:
            users = users.select_for_update()
        if isinstance(user, User):
            user = user.pk
        if isinstance(user, str):
            return users.get(username=user)
        return users.get(pk=user)


    @transaction.atomic
    def deduct_credit(self, user: 'User|int|str', value: int, source: str,
                      **options) -> int:
        '''
        扣除信用分并记录，至多扣到0分，原子化操作

        :param user: 扣除的用户，可以是对象、主键或用户名
        :type user: User|int|str
        :param value: 希望扣除的分值
        :type value: int
        :param source: 扣分来源，可以是“地下室”等应用名，尽量简单
        :type source: str
        :return: 实际扣除的信用分
        :rtype: int
        '''
        update_user = self.get_user(user, update=True)
        deduct_value = min(value, update_user.credit)
        self._record_credit_modify(
            update_user, -value, source=source,
            true_value=-deduct_value,
            **options,
        )
        update_user.credit -= deduct_value
        update_user.save(update_fields=['credit'])
        if isinstance(user, User):
            user.credit = update_user.credit
        return deduct_value

    def _record_credit_modify(self, user: 'User', value: int, source: str, **options):
        pass


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

    credit = models.IntegerField('信用分', default=3)

    class Type(models.TextChoices):
        PERSON = 'Person', '自然人'
        ORG = 'Organization', '组织'
        SPECIAL = '', '特殊用户'

    utype: 'str|Type' = models.CharField(
        '用户类型', max_length=20,
        choices=Type.choices,
        default='', blank=True,
    )

    objects: UserManager = UserManager()
