from django.contrib import admin

from utils.admin_utils import *
from record.models import *


# @admin.register(PageLog)
# class PageLogAdmin(admin.ModelAdmin):
#     list_display = ["user", "type", "page", "time"]
#     list_filter = ["type", "time", "platform"]
#     search_fields =  ["user__username", "page"]
#     date_hierarchy = "time"


# @admin.register(ModuleLog)
# class ModuleLogAdmin(admin.ModelAdmin):
#     list_display = ["user", "type", "page", "module_name", "time"]
#     list_filter = ["type", "module_name", "time", "platform", "page"]
#     search_fields = ["user__username", "page", "module_name"]
#     date_hierarchy = "time"
