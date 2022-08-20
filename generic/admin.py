from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from generic.models import *


@admin.register(User)
class MyUserAdmin(UserAdmin):
    list_display = ['id', 'username', 'credit', 'utype', 'is_staff', 'is_superuser']
    list_editable = ['credit']
    list_filter = ['utype', 'is_superuser', 'is_staff', 'groups', 'is_active']
    fieldsets = [
        (None, {'fields': ('username', 'password')}),
        ('自定义信息', {'fields': ['credit', 'YQpoint', 'utype']}),
        # 内置部分
        ('权限', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ['collapse']
        }),
        ('内置信息', {'fields': ('first_name', 'last_name', 'email'), 'classes': ['collapse']}),
        ('日期', {'fields': ('last_login', 'date_joined'), 'classes': ['collapse']}),
    ]


@admin.register(CreditRecord)
class CreditRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'source', 'delta', 'overflow', 'time']
    list_filter = ['time', 'source', 'overflow', 'old_credit', 'new_credit']
    search_fields = ['user', 'source']
    date_hierarchy = 'time'
