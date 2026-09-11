"""
Serializers of the grades mini-program API (``timetable/README.md`` §6.2).

The endpoints take no request body; these serializers only document the
``GradesOut`` response produced by ``academic_record.services`` and the
``{code, message}`` error envelope for the OpenAPI schema.
"""
from rest_framework import serializers

__all__ = [
    'GradesErrorSerializer',
    'GradeSummarySerializer',
    'GradeRowSerializer',
    'TermScoresSerializer',
    'GradesOutSerializer',
]


class GradesErrorSerializer(serializers.Serializer):
    """Canonical ``{code, message}`` error body."""

    code = serializers.CharField(help_text='Stable machine-readable error code')
    message = serializers.CharField(help_text='User-facing message')


class GradeSummarySerializer(serializers.Serializer):
    credits = serializers.FloatField(help_text='学分之和（有学分的课程）')
    gpa = serializers.FloatField(
        allow_null=True,
        help_text='学分加权绩点 Σ(绩点×学分)/Σ学分；没有可计算的课程时为 null')


class GradeRowSerializer(serializers.Serializer):
    term_code = serializers.CharField(help_text='学期代码，如 25-26-1')
    course_code = serializers.CharField(allow_blank=True)
    class_no = serializers.CharField(allow_blank=True)
    name = serializers.CharField()
    course_type = serializers.CharField(allow_blank=True)
    credits = serializers.FloatField(allow_null=True)
    score = serializers.CharField(
        allow_blank=True, help_text='门户成绩原文，如 85 / P / 合格 / W')
    score_numeric = serializers.FloatField(allow_null=True)
    gpa = serializers.FloatField(allow_null=True)


class TermScoresSerializer(serializers.Serializer):
    term_code = serializers.CharField()
    summary = GradeSummarySerializer()
    rows = GradeRowSerializer(many=True)


class GradesOutSerializer(serializers.Serializer):
    stored = serializers.BooleanField(
        help_text='本次返回的数据是否已存储在平台（需成绩授权）')
    fetched_at = serializers.DateTimeField(
        allow_null=True, help_text='数据获取时间，YYYY-MM-DDTHH:MM:SS')
    summary = GradeSummarySerializer()
    terms = TermScoresSerializer(many=True)
