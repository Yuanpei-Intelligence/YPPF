from django.contrib import admin

from dormitory.models import *
from generic.admin import UserAdmin

admin.site.register(Dormitory)

@admin.register(Agreement)
class DormitoryAgreementAdmin(admin.ModelAdmin):
    list_display = ['user', 'sign_time']
    search_fields = ['user__username', 'user__name']

@admin.register(DormitoryAssignment)
class DormitoryAssignmentAdmin(admin.ModelAdmin):
    list_display = ['dormitory', 'user', 'bed_id', 'time']
    list_filter = ['bed_id', 'time']
    search_fields = ['dormitory', *UserAdmin.suggest_search_fields('user'), 'time']
