from django.contrib import admin
from app.models import *

# Register your models here.
class NaturalPersonAdmin(admin.ModelAdmin):
    fieldsets = (
        ["Commom Attributes", {"fields": ("person_id", "name", "gender", "identity", "YQPoint")}],
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
    ]
    search_fields = ("person_id__username", "name")

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

class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["oname"]
    search_fields = ("oname",)


class PositionAdmin(admin.ModelAdmin):
    list_display = ["person", "org", "pos"]
    search_fields = ("person__name", "org__oname", "pos")


admin.site.register(NaturalPerson, NaturalPersonAdmin)
admin.site.register(Freshman, FreshmanAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(Position, PositionAdmin)

admin.site.register(OrganizationType)
admin.site.register(Activity)
admin.site.register(TransferRecord)

admin.site.register(YQPointDistribute)
admin.site.register(Notification)
admin.site.register(Help)
