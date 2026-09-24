from django.contrib import admin

from timetable.models import (
    AcademicTerm,
    CourseCatalogEntry,
    CourseExam,
    ImportLog,
    ReminderLog,
    SubscribeQuota,
    TimetableEntry,
    TimetableEntryOverride,
    TimetableSettings,
)


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'week1_monday', 'total_weeks',
                    'exam_week_start', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['-week1_monday']


class TimetableEntryOverrideInline(admin.TabularInline):
    model = TimetableEntryOverride
    extra = 0
    fields = ['week_start', 'week_end', 'canceled', 'fields', 'updated_at']
    readonly_fields = ['updated_at']


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = [
        'person', 'term', 'source', 'name', 'weekday',
        'start_section', 'end_section', 'week_start', 'week_end',
        'parity', 'role', 'category', 'tag', 'hidden',
    ]
    list_filter = ['term', 'source', 'role', 'category', 'weekday', 'parity', 'hidden']
    search_fields = ['name', 'teacher', 'room', 'tag', 'course_code', 'person__name',
                     'person__person_id__username']
    raw_id_fields = ['person', 'catalog_entry']
    readonly_fields = ['external_key', 'created_at', 'updated_at']
    inlines = [TimetableEntryOverrideInline]


@admin.register(TimetableEntryOverride)
class TimetableEntryOverrideAdmin(admin.ModelAdmin):
    list_display = ['entry', 'week_start', 'week_end', 'canceled', 'updated_at']
    list_filter = ['canceled']
    search_fields = ['entry__name', 'entry__person__name',
                     'entry__person__person_id__username']
    raw_id_fields = ['entry']
    readonly_fields = ['created_at', 'updated_at']


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
                    'show_courses', 'show_college', 'show_activities',
                    'show_appointments', 'show_exams', 'share_show_name']
    search_fields = ['person__name', 'person__person_id__username']
    raw_id_fields = ['person']
    readonly_fields = ['ics_token']


@admin.register(SubscribeQuota)
class SubscribeQuotaAdmin(admin.ModelAdmin):
    list_display = ['user', 'template_key', 'count', 'updated_at']
    list_filter = ['template_key']
    search_fields = ['user__username', 'user__name']
    raw_id_fields = ['user']
    readonly_fields = ['updated_at']


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ['person', 'occurrence_id', 'channel', 'scheduled_for',
                    'sent_at', 'detail']
    list_filter = ['channel']
    search_fields = ['occurrence_id', 'person__name', 'person__person_id__username']
    raw_id_fields = ['person']
    readonly_fields = ['person', 'occurrence_id', 'channel', 'scheduled_for',
                       'sent_at', 'detail']
    date_hierarchy = 'scheduled_for'


@admin.register(CourseCatalogEntry)
class CourseCatalogEntryAdmin(admin.ModelAdmin):
    list_display = ['term', 'course_code', 'class_no', 'name', 'teacher',
                    'credits', 'weeks_text', 'time_text']
    list_filter = ['term', 'category']
    search_fields = ['course_code', 'name', 'name_en', 'teacher', 'department']
    ordering = ['course_code', 'class_no']


@admin.register(CourseExam)
class CourseExamAdmin(admin.ModelAdmin):
    list_display = ['term', 'course_code', 'class_no', 'name', 'teacher',
                    'start', 'end', 'room', 'method']
    list_filter = ['term', 'method']
    search_fields = ['course_code', 'name', 'teacher', 'room']
    date_hierarchy = 'start'
    ordering = ['start', 'course_code']
