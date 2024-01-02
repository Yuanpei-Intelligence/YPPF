from django.contrib import admin

from dormitory.models import *
from generic.admin import UserAdmin

admin.site.register(Dormitory)

admin.site.register(Agreement)

@admin.register(DormitoryAssignment)
class DormitoryAssignmentAdmin(admin.ModelAdmin):
    list_display = ['dormitory', 'user', 'bed_id', 'time']
    list_filter = ['bed_id', 'time']
    search_fields = ['dormitory', *UserAdmin.suggest_search_fields('user'), 'time']
