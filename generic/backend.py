from generic.models import User, PermissionBlacklist
from utils.models.query import sq
from django.contrib.auth.backends import AllowAllUsersModelBackend
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

class BlacklistBackend(AllowAllUsersModelBackend):
    '''
    在django自带的认证后端的基础上，除去在黑名单中记录的用户权限。

    如果在调试模式下运行，has_perm, with_perm将会检查传入的permission string
    是否在数据库中有对应的permission.
    '''
    # Currently not customizing authentication methods
    def get_cancelled(self, user: User) -> set[str]:
        return PermissionBlacklist.get_cancelled_permissions(user)

    def get_user_permissions(self, user: User, obj = None) -> set[str]:
        '''
        获取用户特有的权限(user_permission)，不包括黑名单中的权限。
        '''
        return super().get_user_permissions(user, obj) - self.get_cancelled(user)

    def get_all_permissions(self, user: User, obj = None) -> set[str]:
        '''
        获取用户的所有权限，也就是用户所在组的权限 + 用户自身权限 - 黑名单中的权限
        '''
        return super().get_all_permissions(user, obj) - self.get_cancelled(user)

    def get_group_permissions(self, user: User, obj = None) -> set[str]:
        '''
        获取用户通过其所在组获得的权限，不包括黑名单中的权限。
        '''
        return super().get_group_permissions(user, obj) - self.get_cancelled(user)

    def has_perm(self, user: User, perm: str, obj = None) -> bool:
        '''
        检查用户user是否有perm权限。暂时还不支持对于某一个特定的obj查询。
        '''
        return perm not in self.get_cancelled(user) and super().has_perm(user, perm, obj)

    def has_module_perms(self, user: User, app_label: str) -> bool:
        '''
        检查用户是否有app_label这一应用的权限。如果用户有其中任何一个权限，就认为他是具有这个应用的权限的。
        '''
        return user.is_active and any(
            perm[: perm.index(".")] == app_label
            for perm in self.get_all_permissions(user)
        )

    def with_perm(self, perm: str, is_active=True, include_superusers=True, obj=None) -> list[User]:
        """
        返回所有具有perm权限的用户列表。默认要求用户is_active，且包括超级用户。
        """
        try:
            app_label, codename = perm.split('.')
        except ValueError:
            raise ValueError("Permission string format incorrect")
        # banned_users is a set of str (the username field)
        banned_users = PermissionBlacklist.objects.filter(
            sq((PermissionBlacklist.permission, Permission.codename), codename) &
            sq((
                PermissionBlacklist.permission,
                Permission.content_type,
                ContentType.app_label
            ), app_label)
        ).values_list("user", flat = True)
        # Transform into set for O(log n) lookup
        banned_users = set(banned_users)
        result = []
        for user in super().with_perm(perm, is_active, include_superusers, obj):
            if user.username not in banned_users:
                result.append(user)
        return result
