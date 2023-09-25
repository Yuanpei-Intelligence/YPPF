from django.contrib import admin

from semester.models import Semester, SemesterType


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ['year', 'type', 'start_date', 'end_date']
    list_filter = ['year', 'type']


@admin.register(SemesterType)
class SemesterTypeAdmin(admin.ModelAdmin):
    pass
