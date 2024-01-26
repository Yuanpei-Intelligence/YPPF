from django.db import models

__all__ = ['BasePermission', 'PermissionModelBase']


class BasePermission(models.TextChoices):
    '''权限基类

    用于定义权限，继承此类后，可以在对应类中定义权限，如::

        class UserPermission(BasePermission):
            MANAGE = choice('manage_user', '管理用户')
            AUDIT = choice('audit_user', '审核用户')
            ...
        user.has_perm(UserPermission.MANAGE.perm)

    Attributes:
        perm: 权限字符串，格式为`app_label.codename`，可直接用于`has_perm`判断
    '''
    @property
    def perm(self):
        return f'{self._meta.app_label}.{self.value}'


class PermissionModelBase(models.base.ModelBase):
    '''权限模型元类

    用于自动将`Model.Permission`转换为`Model.Meta.permissions`，以便迁移和产生权限
    同时提供Permission模型属性，以便插入应用数据，生成完整的权限名称

    Example::

        class User(models.Model, metaclass=PermissionModelBase):
            class Permission(BasePermission):
                MANAGE = choice('manage_user', '管理用户')
                AUDIT = choice('audit_user', '审核用户')
                ...
            class Meta:
                # 无需定义permissions
                pass
        assert(User.Permission.MAKE.perm == 'APP_LABEL.manage_user')

    Warning:
        Permission类必须定义在Model类中，且必须命名为`Permission`

    Note:
        在模型中定义Meta和Permission类时无需在意顺序
    '''
    def __new__(cls, name, bases, attrs, **kwargs):
        Permission = attrs.get('Permission')
        if Permission:
            attrs['Meta'].permissions = Permission.choices
        clz = super().__new__(cls, name, bases, attrs, **kwargs)
        clz.Permission._meta = clz._meta  # type: ignore
        return clz
