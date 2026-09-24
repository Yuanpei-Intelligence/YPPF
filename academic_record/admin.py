"""
Admin page of the grade records. Grades are personal data: the page is
read-only, ``raw`` is never rendered, and rows are only ever created by a
portal sync (``academic_record.services.store_scores``).
"""
from django.contrib import admin

from academic_record.models import GradeRecord


@admin.register(GradeRecord)
class GradeRecordAdmin(admin.ModelAdmin):
    list_display = [
        'person', 'term_code', 'course_code', 'name', 'course_type',
        'credits', 'score', 'gpa', 'fetched_at',
    ]
    list_filter = ['term_code', 'course_type']
    search_fields = [
        'person__name', 'person__person_id__username', 'name', 'course_code',
    ]
    raw_id_fields = ['person']
    exclude = ['raw']
    readonly_fields = [
        'person', 'term_code', 'course_code', 'class_no', 'name',
        'course_type', 'credits', 'score', 'score_numeric', 'gpa',
        'fetched_at',
    ]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
