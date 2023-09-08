from django.contrib import admin

from semester.models import Semester, SemesterType


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    pass


@admin.register(SemesterType)
class SemesterTypeAdmin(admin.ModelAdmin):
    pass
