from django.contrib import admin

from semester.models import CalendarEvent, Semester, SemesterType


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ['year', 'type', 'start_date', 'end_date']
    list_filter = ['year', 'type']


@admin.register(SemesterType)
class SemesterTypeAdmin(admin.ModelAdmin):
    pass


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ['kind', 'name', 'start_date', 'end_date', 'follows_weekday']
    list_filter = ['kind']
    search_fields = ['name', 'note']
    date_hierarchy = 'start_date'
    ordering = ['start_date', 'id']
