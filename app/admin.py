from django.contrib import admin
from app.models import *

# Register your models here.
class NaturalPersonAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "person_id",
        "gender",
        "stu_grade",
        "stu_dorm",
        "status",
        "identity",
        "email",
        "stu_class",
        "stu_major",
        "telephone",
        "first_time_login",
    ]
    search_fields = ("person_id", "name")


class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["oname"]
    search_fields = ("oname",)


class PositionAdmin(admin.ModelAdmin):
    list_display = ["person", "org", "pos"]
    search_fields = ("person__pname", "org__oname", "pos__person")


admin.site.register(NaturalPerson, NaturalPersonAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(Position, PositionAdmin)

admin.site.register(OrganizationType)
admin.site.register(Activity)
admin.site.register(TransferRecord)
