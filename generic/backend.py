from django.contrib.auth.backends import AllowAllUsersModelBackend
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet

import utils.models.query as SQ
from generic.models import User, PermissionBlacklist


class BlacklistBackend(AllowAllUsersModelBackend):
    '''
    在django自带的认证后端的基础上，除去在黑名单中记录的用户权限。
    '''

    def _revoked_perms(self, user: User) -> set[str]:
        return PermissionBlacklist.objects.get_revoked_permissions(user)

    def get_user_permissions(self, user: User, obj = None) -> set[str]:
        '''获取用户自身权限，不包括组权限和黑名单中的权限。'''
        return super().get_user_permissions(user, obj) - self._revoked_perms(user)

    def get_all_permissions(self, user: User, obj = None) -> set[str]:
        '''获取用户的所有权限，也就是用户所在组的权限 + 用户自身权限 - 黑名单中的权限'''
        return super().get_all_permissions(user, obj) - self._revoked_perms(user)

    def get_group_permissions(self, user: User, obj = None) -> set[str]:
        '''获取用户通过其所在组获得的权限，不包括黑名单中的权限。'''
        return super().get_group_permissions(user, obj) - self._revoked_perms(user)

    def has_perm(self, user: User, perm: str, obj = None) -> bool:
        '''检查用户的特定权限。暂不支持对于某一个特定的obj查询。'''
        return perm not in self._revoked_perms(user) and super().has_perm(user, perm, obj)

    def has_module_perms(self, user: User, app_label: str) -> bool:
        '''
        检查用户的应用权限
        
        如果用户有其中任何一个权限，就认为他具有这个应用的权限。
        '''
        return user.is_active and any(
            perm[: perm.index('.')] == app_label
            for perm in self.get_all_permissions(user)
        )

    def with_perm(self, perm: str | Permission, is_active: bool = True,
                  include_superusers: bool = True, obj = None) -> QuerySet[User]:
        '''
        返回所有具有perm权限的用户列表。默认要求用户is_active，且包括超级用户。

        Args:
            perm (str | Permission): 权限，字符串格式为app_label.codename
            is_active (bool, optional): 是否要求用户是激活状态，默认为True
            include_superusers (bool, optional): 是否包括超级用户
            obj (Any, optional): 查询对于某一个特定的对象的权限，父类暂不支持

        Returns:
            具有权限的用户集合
        '''
        _M = PermissionBlacklist
        # 父类的with_perm方法会检查传入的perm是否符合格式
        users: QuerySet[User] = super().with_perm(perm, is_active, include_superusers, obj)
        if isinstance(perm, str):
            app_label, codename = perm.split('.')
            banned_records = _M.objects.filter(
                SQ.sq((_M.permission, Permission.codename), codename),
                SQ.sq((_M.permission, Permission.content_type, ContentType.app_label), app_label)
            )
        elif isinstance(perm, Permission):
            banned_records = SQ.sfilter(_M.permission, perm)
        return users.exclude(pk__in=SQ.qsvlist(banned_records, _M.user, 'pk'))
