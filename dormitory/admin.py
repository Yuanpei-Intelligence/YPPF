from django.contrib import admin

from dormitory.models import *
from generic.admin import UserAdmin

@admin.register(Dormitory)
class DormitoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'capacity', 'gender')
    search_fields = ('id',)

@admin.register(Agreement)
class DormitoryAgreementAdmin(admin.ModelAdmin):
    list_display = ['user', 'sign_time']
    search_fields = ['user__username', 'user__name']

@admin.register(DormitoryAssignment)
class DormitoryAssignmentAdmin(admin.ModelAdmin):
    list_display = ['dormitory', 'user', 'bed_id', 'time']
    list_filter = ['bed_id', 'time']
    search_fields = ['dormitory__id', *UserAdmin.suggest_search_fields('user'), 'time']
