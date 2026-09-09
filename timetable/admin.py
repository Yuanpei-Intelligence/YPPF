from django.contrib import admin

from timetable.models import (
    AcademicTerm,
    ImportLog,
    TimetableEntry,
    TimetableSettings,
)


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'week1_monday', 'total_weeks', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['-week1_monday']


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = [
        'person', 'term', 'source', 'name', 'weekday',
        'start_section', 'end_section', 'week_start', 'week_end',
        'parity', 'hidden',
    ]
    list_filter = ['term', 'source', 'weekday', 'parity', 'hidden']
    search_fields = ['name', 'teacher', 'room', 'person__name',
                     'person__person_id__username']
    raw_id_fields = ['person']
    readonly_fields = ['external_key', 'created_at', 'updated_at']


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = ['person', 'term', 'source', 'status', 'entries_count',
                    'created_at']
    list_filter = ['term', 'source', 'status']
    search_fields = ['person__name', 'person__person_id__username']
    raw_id_fields = ['person']
    readonly_fields = ['person', 'term', 'source', 'status', 'entries_count',
                       'message', 'created_at']


@admin.register(TimetableSettings)
class TimetableSettingsAdmin(admin.ModelAdmin):
    list_display = ['person', 'reminder_enabled', 'reminder_minutes',
                    'show_college', 'show_activities', 'show_appointments',
                    'share_show_name']
    search_fields = ['person__name', 'person__person_id__username']
    raw_id_fields = ['person']
    readonly_fields = ['ics_token']
