from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as _UserAdmin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet

from utils.models.query import svlist
from utils.admin_utils import *
from generic.models import *
from generic.models import to_acronym


# 后台显示
admin.site.site_title = '元培智慧书院管理后台'
admin.site.site_header = '元培智慧书院 - 管理后台'


# Django自带模型
@admin.register(ContentType)
class ContentTypeAdmin(admin.ModelAdmin):
    list_display = ['app_label', 'model', 'name']
    list_filter = ['app_label']
    def _check_invalid(self, request, obj: ContentType | None = None):
        if request.user.is_superuser and obj is not None:
            return obj.model_class() is None
        return False

    has_add_permission = _check_invalid
    has_change_permission = _check_invalid
    has_delete_permission = _check_invalid


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'codename']
    list_filter = ['content_type__app_label']

    def _check_failed(self, request, obj=None):
        return False

    has_add_permission = _check_failed
    has_change_permission = _check_failed
    def has_delete_permission(self, request, obj: Permission | None = None):
        if request.user.is_superuser and obj is not None:
            return ContentTypeAdmin._check_invalid(None, request, obj.content_type)
        return False
    
    actions = []
    @as_action('更新权限名称', actions, update=True)
    def update_name(self, request, queryset: QuerySet[Permission]):
        for perm in queryset:
            content_type: ContentType = perm.content_type
            if content_type.model_class() is None:
                continue
            try:
                prefix, perm_name, model = perm.name.split(maxsplit=2)
            except:
                continue
            model = content_type.name
            perm.name = ' '.join([prefix, perm_name, model])
            perm.save(update_fields=['name'])
        return self.message_user(request, '操作成功')


# 通用模型后台
class UserAdmin(_UserAdmin):
    list_display = [
        'id', 'username', 'name',
        'credit', 'YQpoint', 'utype', 'is_staff', 'is_superuser',
    ]
    # list_editable = ['credit']
    search_fields = ['id', 'username', 'name', 'pinyin', 'acronym']
    @classmethod
    def suggest_search_fields(cls, user_field: str = 'user'):
        return [f'{user_field}__{field}' for field in cls.search_fields[1:]]

    list_filter = [
        'utype', 'is_superuser', 'is_staff', 'groups',
        'active', 'is_active',
    ]
    fieldsets = [
        (None, {'fields': ('username', 'name', 'acronym', 'pinyin', 'password')}),
        ('自定义信息', {'fields': ['credit', 'YQpoint', 'utype', 'is_newuser', 'active']}),
        # 内置部分
        ('权限', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ['collapse']
        }),
        ('内置信息', {'fields': ('first_name', 'last_name', 'email'), 'classes': ['collapse']}),
        ('日期', {'fields': ('last_login', 'date_joined'), 'classes': ['collapse']}),
    ]
    actions = []

    @as_action('同步用户类型', actions, atomic=True)
    def sync_user_type(self, request, queryset):
        from app.models import NaturalPerson, Organization
        User.objects.filter(id__in=svlist(Organization.organization_id)
            ).select_for_update().update(utype=User.Type.ORG)
        User.objects.filter(id__in=svlist(NaturalPerson.person_id)
            ).exclude(utype__in=User.Type.Persons()
            ).select_for_update().update(utype=User.Type.PERSON)
        return self.message_user(request, '操作成功')


    @as_action('同步用户名称', actions, atomic=True)
    def sync_user_name(self, request, queryset):
        from app.models import NaturalPerson, Organization
        org_users = User.objects.filter(id__in=svlist(Organization.organization_id)
            ).select_for_update().select_related('organization')
        for user in org_users:
            user.name = user.organization.get_display_name()
        User.objects.bulk_update(org_users, ['name'])
        person_users = User.objects.filter(id__in=svlist(NaturalPerson.person_id)
            ).select_for_update().select_related('naturalperson')
        for user in person_users:
            user.name = user.naturalperson.get_display_name()
        User.objects.bulk_update(person_users, ['name'])
        return self.message_user(request, '操作成功')


    def _update_acronym(self, queryset: QuerySet[User]):
        for user in queryset:
            user.acronym = to_acronym(user.name)
        User.objects.bulk_update(queryset, ['acronym'])

    @as_action('更新全部缩写', actions, atomic=True)
    def renew_acronym(self, request, queryset):
        self._update_acronym(User.objects.select_for_update())
        return self.message_user(request, '更新全部缩写成功!')

    @as_action('更新名称缩写', actions, update=True)
    def renew_pinyin(self, request, queryset):
        self._update_acronym(queryset)
        return self.message_user(request, '更新名称缩写成功!')


    @as_action('重置信用分', actions, atomic=True)
    def refresh_credit(self, request, queryset):
        User.objects.bulk_recover_credit(queryset, User.MAX_CREDIT, '用户：重置')
        return self.message_user(request, '操作成功!')

    @as_action('恢复信用分 1分', actions, atomic=True)
    def recover_credit(self, request, queryset):
        User.objects.bulk_recover_credit(queryset, 1, '用户：恢复')
        return self.message_user(request, '操作成功!')

    @as_action('全体恢复信用分 1分', actions, atomic=True)
    def recover(self, request, queryset):
        User.objects.bulk_recover_credit(User.objects.all(), 1, '用户：全体恢复')
        return self.message_user(request, '操作成功!')

admin.site.register(User, UserAdmin)

@admin.register(PermissionBlacklist)
class PermissionBlacklistAdmin(admin.ModelAdmin):
    list_display = ['user', 'permission']
    search_fields = [*UserAdmin.suggest_search_fields(), 'permission__name']

@admin.register(CreditRecord)
class CreditRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'source', 'delta', 'overflow', 'time']
    list_filter = [
        'time', 'source', 'overflow', 'old_credit', 'new_credit',
        get_sign_filter('delta', '变化类型'),
    ]
    search_fields = [*UserAdmin.suggest_search_fields(), 'source']
    date_hierarchy = 'time'


@admin.register(YQPointRecord)
class YQPointRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'source', 'delta', 'time']
    list_filter = [
        'time', 'source_type',
        get_sign_filter('delta', '变化类型',
                        choices=(('+', '收入'), ('-', '支出'))),
    ]
    search_fields = [*UserAdmin.suggest_search_fields(), 'source']
    date_hierarchy = 'time'
