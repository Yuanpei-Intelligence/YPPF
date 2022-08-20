from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from generic.models import User


@admin.register(User)
class MyUserAdmin(UserAdmin):
    list_display = ['id', 'username', 'credit', 'utype', 'is_staff', 'is_superuser']
    list_editable = ['credit']
    list_filter = ['utype', 'is_superuser', 'is_staff', 'groups', 'is_active']
    fieldsets = UserAdmin.fieldsets + (
        ('自定义信息', {'fields': ['credit', 'YQpoint', 'utype']}),
    )
