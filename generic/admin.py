import pypinyin
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import QuerySet
from generic.models import *
from generic.models import to_acronym
from boottest.admin_utils import *


@admin.register(User)
class MyUserAdmin(UserAdmin):
    list_display = [
        'id', 'username', 'name',
        'credit', 'utype', 'is_staff', 'is_superuser',
    ]
    list_editable = ['credit']
    search_fields = ['id', 'username', 'name', 'acronym']
    list_filter = ['utype', 'is_superuser', 'is_staff', 'groups', 'is_active']
    fieldsets = [
        (None, {'fields': ('username', 'name', 'acronym', 'password')}),
        ('自定义信息', {'fields': ['credit', 'YQpoint', 'utype']}),
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
        User.objects.filter(id__in=Organization.objects.values_list('organization_id')
            ).select_for_update().update(utype=User.Type.ORG)
        User.objects.filter(id__in=NaturalPerson.objects.values_list('person_id')
            ).select_for_update().update(utype=User.Type.PERSON)
        return self.message_user(request, '操作成功')


    @as_action('同步用户名称', actions, atomic=True)
    def sync_user_name(self, request, queryset):
        from app.models import NaturalPerson, Organization
        org_users = User.objects.filter(id__in=Organization.objects.values_list('organization_id')
            ).select_for_update().select_related('organization')
        for user in org_users:
            user.name = user.organization.get_display_name()
        User.objects.bulk_update(org_users, ['name'])
        person_users = User.objects.filter(id__in=NaturalPerson.objects.values_list('person_id')
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


@admin.register(CreditRecord)
class CreditRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'source', 'delta', 'overflow', 'time']
    list_filter = ['time', 'source', 'overflow', 'old_credit', 'new_credit']
    search_fields = ['user', 'source']
    date_hierarchy = 'time'
