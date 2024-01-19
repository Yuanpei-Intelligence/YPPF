from generic.models import User, PermissionBlacklist
from boot.config import DEBUG
from django.contrib.auth.backends import AllowAllUsersModelBackend
from django.contrib.auth.models import Permission

class BlacklistBackend(AllowAllUsersModelBackend):
    '''
    在django自带的认证后端的基础上，除去在黑名单中记录的用户权限。

    如果在调试模式下运行，has_perm, with_perm将会检查传入的permission string
    是否在数据库中有对应的permission.
    '''
    # Currently not customizing authentication methods
    def get_user_permissions(self, user_obj: User, obj = None) -> set[str]:
        return super().get_user_permissions(user_obj, obj) - \
            PermissionBlacklist.get_cancelled_permissions(user_obj)

    def get_all_permissions(self, user_obj: User, obj = None) -> set[str]:
        return super().get_all_permissions(user_obj, obj) - \
            PermissionBlacklist.get_cancelled_permissions(user_obj)

    def get_group_permissions(self, user_obj: User, obj = None) -> set[str]:
        return super().get_group_permissions(user_obj, obj) - \
            PermissionBlacklist.get_cancelled_permissions(user_obj)

    @staticmethod
    def _check_permission_string(perm: str):
        '''
        In debug mode, hecks if the permission string `perm` is included in the database.
        This function is intended to alert the programmer of possible typos.

        If the permission string isn't included in the database, raise ValueError.
        '''
        if not DEBUG:
            return
        # Valid permission strings have the form app_name.permission_name
        # dot_pos is -1 if there is no '.' in `perm`
        dot_pos = perm.find('.')
        if dot_pos == -1 or not Permission.objects.filter(
            content_type__app_label = perm[:dot_pos], codename = perm[dot_pos + 1:]
        ).exists():
            raise ValueError(f'Unknown permission string "{perm}"')

    def has_perm(self, user_obj: User, perm, obj = None):
        type(self)._check_permission_string(perm)
        return perm not in PermissionBlacklist.get_cancelled_permissions(user_obj) \
            and super().has_perm(user_obj, perm, obj)

    def has_module_perms(self, user_obj: User, app_label: str) -> bool:
        return user_obj.is_active and any(
            perm[: perm.index(".")] == app_label
            for perm in self.get_all_permissions(user_obj)
        )

    def with_perm(self, perm, is_active= True, include_superusers = True, obj = None) -> list[User]:
        """
        Return users that have permission "perm". By default, filter out
        inactive users and include superusers.

        "perm" should be of type str or Permission.
        """
        type(self)._check_permission_string(perm)
        return list(filter(
            lambda user: perm not in PermissionBlacklist.get_cancelled_permissions(user),
            super().with_perm(perm, is_active, include_superusers, obj)
        ))
