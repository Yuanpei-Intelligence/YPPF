"""
Serializers of the timetable mini-program API. Contract: ``timetable/README.md`` §4.6
(§6.1 subscribe messages, §6.3 course catalog).

Response payloads for the week view are plain dicts produced by
``timetable.services``; the serializers below document their shape for the
OpenAPI schema and validate request bodies.
"""
from __future__ import annotations

from datetime import time

from rest_framework import serializers

from semester.models import CalendarEvent
from timetable import reminders
from timetable.models import CourseCatalogEntry, TimetableEntry, TimetableSettings

__all__ = [
    'CalendarEventSerializer',
    'WeekDaySerializer',
    'TermSerializer',
    'TermsResponseSerializer',
    'WeekQuerySerializer',
    'OccurrenceSerializer',
    'WeekViewSerializer',
    'EntrySerializer',
    'EntryInSerializer',
    'ImportPortalSerializer',
    'ImportTextSerializer',
    'LessonBlockSerializer',
    'DryRunResponseSerializer',
    'ImportOutSerializer',
    'SettingsSerializer',
    'IcsSerializer',
    'ErrorSerializer',
    'SubscribeTemplateSerializer',
    'SubscribeTemplatesSerializer',
    'SubscribeGrantSerializer',
    'SubscribeGrantOutSerializer',
    'CatalogQuerySerializer',
    'CatalogSlotSerializer',
    'CatalogEntrySerializer',
]

TIME_INPUT_FORMATS = ['%H:%M', '%H:%M:%S']
MAX_SECTION = 20
MAX_WEEK = 30
CALENDAR_KINDS = list(CalendarEvent.Kind.values)


class ErrorSerializer(serializers.Serializer):
    """Canonical ``{code, message}`` error body."""

    code = serializers.CharField(help_text='Stable machine-readable error code')
    message = serializers.CharField(help_text='User-facing message')
    errors = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False, help_text='Field errors of a validation failure')


class CalendarEventSerializer(serializers.Serializer):
    """One university calendar (校历) event, §6.4."""

    kind = serializers.ChoiceField(choices=CALENDAR_KINDS)
    start = serializers.DateField()
    end = serializers.DateField(help_text='Inclusive')
    name = serializers.CharField()
    follows_weekday = serializers.IntegerField(
        allow_null=True, help_text='swap only: weekday whose timetable applies, 1=Mon..7=Sun')


class WeekDaySerializer(serializers.Serializer):
    """Calendar label of one date of the week view, §6.4."""

    date = serializers.DateField()
    weekday = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=CALENDAR_KINDS, allow_null=True)
    label = serializers.CharField(allow_null=True)
    follows_weekday = serializers.IntegerField(allow_null=True)


class TermSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    week1_monday = serializers.DateField()
    total_weeks = serializers.IntegerField()
    current_week = serializers.IntegerField(allow_null=True)
    section_times = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text='{"1": ["08:00", "08:50"], ...}')
    calendar = CalendarEventSerializer(
        many=True, help_text='Calendar events overlapping the teaching weeks, ordered')


class TermsResponseSerializer(serializers.Serializer):
    current = TermSerializer(allow_null=True)
    terms = TermSerializer(many=True)


class WeekQuerySerializer(serializers.Serializer):
    term = serializers.CharField(required=False, allow_blank=True,
                                 help_text='Term code, default current term')
    week = serializers.IntegerField(required=False,
                                    help_text='Teaching week, default this week')


class TodaySerializer(serializers.Serializer):
    date = serializers.DateField()
    weekday = serializers.IntegerField()
    week = serializers.IntegerField(allow_null=True)


class OccurrenceSerializer(serializers.Serializer):
    id = serializers.CharField()
    source = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=['course', 'college', 'activity', 'appoint', 'custom'])
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    location = serializers.CharField(allow_blank=True)
    start = serializers.CharField(help_text='YYYY-MM-DDTHH:MM:SS, local time')
    end = serializers.CharField(help_text='YYYY-MM-DDTHH:MM:SS, local time')
    date = serializers.DateField()
    week = serializers.IntegerField()
    weekday = serializers.IntegerField()
    start_section = serializers.IntegerField(allow_null=True)
    end_section = serializers.IntegerField(allow_null=True)
    color_key = serializers.CharField(allow_blank=True)
    status = serializers.CharField(allow_blank=True)
    ref = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    hidden = serializers.BooleanField()


class SourceLegendSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class WeekViewSerializer(serializers.Serializer):
    term = TermSerializer()
    week = serializers.IntegerField()
    week_dates = serializers.ListField(child=serializers.DateField())
    days = WeekDaySerializer(many=True, help_text='One per week_dates entry')
    today = TodaySerializer()
    occurrences = OccurrenceSerializer(many=True)
    conflicts = serializers.ListField(
        child=serializers.ListField(child=serializers.CharField()))
    sources = SourceLegendSerializer(many=True)


class EntrySerializer(serializers.ModelSerializer):
    """Read shape of a stored entry."""

    term = serializers.CharField(source='term.code', read_only=True)
    start_time = serializers.TimeField(format='%H:%M', read_only=True)
    end_time = serializers.TimeField(format='%H:%M', read_only=True)

    class Meta:
        model = TimetableEntry
        fields = [
            'id', 'term', 'source', 'name', 'course_code', 'class_no',
            'teacher', 'room', 'weekday', 'start_section', 'end_section',
            'start_time', 'end_time', 'week_start', 'week_end', 'parity',
            'note', 'hidden', 'color',
        ]
        read_only_fields = fields


class EntryInSerializer(serializers.Serializer):
    """
    Write shape of a manual entry. ``start_time``/``end_time`` may be omitted
    when sections are given (they are filled from the term's section table);
    ``start_section``/``end_section`` may be 0 when explicit times are given.
    Pass the target ``AcademicTerm`` as ``context['term']``.
    """

    term = serializers.CharField(required=False, allow_blank=True, max_length=16)
    name = serializers.CharField(max_length=100)
    course_code = serializers.CharField(required=False, allow_blank=True, max_length=32)
    class_no = serializers.CharField(required=False, allow_blank=True, max_length=16)
    teacher = serializers.CharField(required=False, allow_blank=True, max_length=100)
    room = serializers.CharField(required=False, allow_blank=True, max_length=100)
    weekday = serializers.IntegerField(min_value=1, max_value=7)
    start_section = serializers.IntegerField(min_value=0, max_value=MAX_SECTION)
    end_section = serializers.IntegerField(min_value=0, max_value=MAX_SECTION)
    start_time = serializers.TimeField(required=False, input_formats=TIME_INPUT_FORMATS)
    end_time = serializers.TimeField(required=False, input_formats=TIME_INPUT_FORMATS)
    week_start = serializers.IntegerField(min_value=1, max_value=MAX_WEEK)
    week_end = serializers.IntegerField(min_value=1, max_value=MAX_WEEK)
    parity = serializers.ChoiceField(
        choices=TimetableEntry.Parity.choices, required=False,
        default=TimetableEntry.Parity.ALL)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)
    hidden = serializers.BooleanField(required=False)
    color = serializers.RegexField(
        r'^#[0-9a-fA-F]{6}$', required=False, allow_blank=True, max_length=7)

    _ENTRY_FIELDS = (
        'name', 'course_code', 'class_no', 'teacher', 'room', 'weekday',
        'start_section', 'end_section', 'start_time', 'end_time',
        'week_start', 'week_end', 'parity', 'note', 'hidden', 'color',
    )

    def validate(self, attrs):
        # Cross-field rules are checked on the merged result so a partial
        # update cannot leave an entry inconsistent.
        merged = {}
        for name in self._ENTRY_FIELDS:
            if name in attrs:
                merged[name] = attrs[name]
            elif self.instance is not None:
                merged[name] = getattr(self.instance, name)
        start_section = merged.get('start_section', 0)
        end_section = merged.get('end_section', 0)
        if start_section > end_section:
            raise serializers.ValidationError(
                {'end_section': '结束节不能早于起始节'})
        if merged.get('week_start', 1) > merged.get('week_end', 1):
            raise serializers.ValidationError({'week_end': '结束周不能早于起始周'})
        term = self.context.get('term')
        if term is not None and merged.get('week_end', 1) > term.total_weeks:
            raise serializers.ValidationError(
                {'week_end': f'结束周不能超过学期总周数 {term.total_weeks}'})
        start_time = merged.get('start_time')
        end_time = merged.get('end_time')
        if start_section >= 1 and end_section >= 1 and term is not None:
            sections_changed = 'start_section' in attrs or 'end_section' in attrs
            if start_time is None or (sections_changed and 'start_time' not in attrs):
                start_time = term.section_time(start_section)[0]
                attrs['start_time'] = start_time
            if end_time is None or (sections_changed and 'end_time' not in attrs):
                end_time = term.section_time(end_section)[1]
                attrs['end_time'] = end_time
        if start_time is None or end_time is None:
            raise serializers.ValidationError(
                {'start_time': '未指定节次时必须填写开始和结束时间'})
        if not isinstance(start_time, time) or not isinstance(end_time, time):
            raise serializers.ValidationError({'start_time': '时间格式错误'})
        if start_time >= end_time:
            raise serializers.ValidationError({'end_time': '结束时间必须晚于开始时间'})
        return attrs


class ImportPortalSerializer(serializers.Serializer):
    term = serializers.CharField(required=False, allow_blank=True, max_length=16)
    username = serializers.CharField(required=False, allow_blank=True, max_length=32)
    password = serializers.CharField(
        required=False, allow_blank=True, max_length=128, write_only=True,
        style={'input_type': 'password'}, trim_whitespace=False)
    consent_timetable = serializers.BooleanField(required=False)


class ImportTextSerializer(serializers.Serializer):
    term = serializers.CharField(required=False, allow_blank=True, max_length=16)
    text = serializers.CharField(max_length=1_000_000, trim_whitespace=False)
    dry_run = serializers.BooleanField(required=False, default=False)


class LessonBlockSerializer(serializers.Serializer):
    name = serializers.CharField()
    teacher = serializers.CharField(allow_blank=True)
    room = serializers.CharField(allow_blank=True)
    course_code = serializers.CharField(allow_blank=True)
    class_no = serializers.CharField(allow_blank=True)
    weekday = serializers.IntegerField()
    start_section = serializers.IntegerField()
    end_section = serializers.IntegerField()
    week_start = serializers.IntegerField()
    week_end = serializers.IntegerField()
    parity = serializers.IntegerField()
    raw = serializers.CharField(allow_blank=True)
    note = serializers.CharField(allow_blank=True)


class DryRunResponseSerializer(serializers.Serializer):
    format = serializers.ChoiceField(
        choices=['portal_html', 'elective', 'portal_json', 'unknown'])
    blocks = LessonBlockSerializer(many=True)


class ImportOutSerializer(serializers.Serializer):
    term = serializers.CharField()
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    removed = serializers.IntegerField()
    total = serializers.IntegerField()


class SettingsSerializer(serializers.ModelSerializer):
    """Read/write shape of ``TimetableSettings`` (the ICS token is not exposed)."""

    reminder_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)

    class Meta:
        model = TimetableSettings
        fields = [
            'reminder_enabled', 'reminder_minutes', 'show_college',
            'show_activities', 'show_appointments', 'share_show_name',
        ]


class IcsSerializer(serializers.Serializer):
    url = serializers.URLField()
    token = serializers.CharField()


class SubscribeTemplateSerializer(serializers.Serializer):
    template_id = serializers.CharField(
        allow_null=True, help_text='WeChat template id; null when not configured')


class SubscribeTemplatesSerializer(serializers.Serializer):
    """Template ids by key; the client only requests configured ones."""

    class_reminder = SubscribeTemplateSerializer()


class SubscribeGrantSerializer(serializers.Serializer):
    template_key = serializers.CharField(max_length=32)
    count = serializers.IntegerField(
        required=False, default=1, min_value=1, max_value=1000,
        help_text='Number of accepts to record (server caps the stored total)')

    def validate_template_key(self, value: str) -> str:
        if value not in reminders.subscribe_template_keys():
            raise serializers.ValidationError('未知的订阅消息模板。')
        return value


class SubscribeGrantOutSerializer(serializers.Serializer):
    template_key = serializers.CharField()
    count = serializers.IntegerField(help_text='Unused grants now stored')


class CatalogQuerySerializer(serializers.Serializer):
    term = serializers.CharField(required=False, allow_blank=True,
                                 help_text='Term code, default current term')
    q = serializers.CharField(required=False, allow_blank=True, max_length=64,
                              help_text='Matches name / code / teacher (icontains)')


class CatalogSlotSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(required=False)
    start_section = serializers.IntegerField(required=False)
    end_section = serializers.IntegerField(required=False)
    week_start = serializers.IntegerField(required=False)
    week_end = serializers.IntegerField(required=False)
    parity = serializers.IntegerField(required=False)
    room = serializers.CharField(required=False, allow_blank=True)


class CatalogEntrySerializer(serializers.ModelSerializer):
    """Read shape of a course catalog row for the manual-entry form."""

    credits = serializers.FloatField(allow_null=True, read_only=True)
    slots = CatalogSlotSerializer(many=True, read_only=True)

    class Meta:
        model = CourseCatalogEntry
        fields = ['id', 'course_code', 'name', 'class_no', 'teacher',
                  'credits', 'time_text', 'slots']
        read_only_fields = fields
