from django.contrib import admin
from app.models import *

# Register your models here.
class NaturalPersonAdmin(admin.ModelAdmin):
    list_display = [
        "pname",
        "person_id",
        "pgender",
        "pyear",
        "pdorm",
        "pstatus",
        "Identity",
        "pemail",
        "pclass",
        "pmajor",
        "ptel",
        "firstTimeLogin",
    ]
    search_fields = ("person_id", "pname")


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
