from django.contrib import admin
from django.utils.safestring import mark_safe
from app.models import *

# Register your models here.
admin.site.site_title = '元培成长档案管理后台'
admin.site.site_header = '元培成长档案 - 管理后台'


@admin.register(NaturalPerson)
class NaturalPersonAdmin(admin.ModelAdmin):
    fieldsets = (
        ["Commom Attributes", {"fields": (
            "person_id", "name", "nickname", "gender", "identity",
            "YQPoint", "YQPoint_Bonus", "wechat_receive_level")}],
        [
            "Student Attributes",
            {
                "classes": ("collapse",),
                "fields": ("stu_grade", "stu_dorm", "stu_class", "stu_major",
                "show_gender", "show_email", "show_tel", "show_major", "show_dorm"),
                # "show_nickname"
            },
        ],
    )
    list_display = [
        "person_id",
        "name",
        "identity",
        "first_time_login",
    ]
    search_fields = ("person_id__username", "name")
    list_filter = ("stu_grade", "status", "identity", "first_time_login", "wechat_receive_level")

@admin.register(Freshman)
class FreshmanAdmin(admin.ModelAdmin):
    list_display = [
        "sid",
        "name",
        "place",
        "grade",
        "status",
    ]
    search_fields = ("sid", "name")
    list_filter = ("status", "grade", "place")


@admin.register(OrganizationType)
class OrganizationTypeAdmin(admin.ModelAdmin):
    list_display = ["otype_id", "otype_name", "incharge", "job_name_list", "control_pos_threshold"]
    search_fields = ("oname", "otype", "incharge__name", "job_name_list")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["organization_id", "oname", "otype", "Managers"]
    search_fields = ("oname", "otype")
    list_filter = ("otype", )

    def Managers(self, obj):
        display = ''
        all_pos = sorted(Position.objects.activated().filter(
                org=obj, is_admin=True).values_list(
                    'pos', flat=True).distinct())
        for pos in all_pos:
            managers = Position.objects.activated().filter(
                org=obj, pos=pos, is_admin=True)
            if managers:
                display += f'{obj.otype.get_name(pos)}：'
                names = managers.values_list('person__name', flat=True)
                display += f"<li>{'、'.join(names)}</li>"
        if not display:
            display = '暂无'
        return mark_safe(display)
    Managers.short_description = "管理者"


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ["person", "org", "pos", "pos_name", "is_admin"]
    search_fields = ("person__name", "org__oname")
    list_filter = ('pos', 'is_admin')
    list_display_links = ('person', 'org')

    def pos_name(self, obj):
        return obj.org.otype.get_name(obj.pos)
    pos_name.short_description = "职位名称"



admin.site.register(Activity)
admin.site.register(TransferRecord)

admin.site.register(YQPointDistribute)
admin.site.register(Notification)
admin.site.register(Help)
admin.site.register(ModifyRecord)
