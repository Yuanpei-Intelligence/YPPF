"""
Serializers of the timetable mini-program API. Contract: ``timetable/README.md`` §4.6
(§6.1 subscribe messages, §6.3 course catalog, §6.5 agenda, §8 catalog
links, scoped edits, tags, exams and share assets, §10 term overview).

Response payloads for the week view, the agenda, the term overview and the
settings are plain
dicts produced by ``timetable.services``; the serializers below document
their shape for the OpenAPI schema and validate request bodies.
"""
from __future__ import annotations

from datetime import time
from types import SimpleNamespace

from rest_framework import serializers

from semester.models import CalendarEvent
from timetable import reminders
from timetable.exams import ENTRY_EXAM_NOTE, entry_exam_window, exams_for_entries
from timetable.models import (
    TAG_MAX_LENGTH,
    CourseCatalogEntry,
    CourseExam,
    TimetableEntry,
    TimetableEntryOverride,
    TimetableSettings,
)
from timetable.services import (
    AGENDA_MAX_DAYS,
    NOTE_MAX_LENGTH,
    OVERVIEW_SLOT_KINDS,
    SCOPES,
)
from timetable.sources.base import DATETIME_FORMAT

__all__ = [
    'CalendarEventSerializer',
    'WeekDaySerializer',
    'TermSerializer',
    'TermsResponseSerializer',
    'WeekQuerySerializer',
    'OccurrenceSerializer',
    'WeekViewSerializer',
    'AgendaQuerySerializer',
    'AgendaDaySerializer',
    'AgendaSerializer',
    'OverviewSlotSerializer',
    'OverviewExamSerializer',
    'OverviewSerializer',
    'EntryCatalogSerializer',
    'EntryOverrideSerializer',
    'EntryExamSerializer',
    'EntrySerializer',
    'EntryInSerializer',
    'EntryScopeSerializer',
    'ImportPortalSerializer',
    'ImportTextSerializer',
    'LessonBlockSerializer',
    'DryRunResponseSerializer',
    'ImportOutSerializer',
    'SettingsSerializer',
    'SettingsOutSerializer',
    'IcsSerializer',
    'ErrorSerializer',
    'SubscribeTemplateSerializer',
    'SubscribeTemplatesSerializer',
    'SubscribeGrantSerializer',
    'SubscribeGrantOutSerializer',
    'CatalogQuerySerializer',
    'CatalogSlotSerializer',
    'CatalogEntrySerializer',
    'CatalogAddSerializer',
    'ShareAssetsSerializer',
]

TIME_INPUT_FORMATS = ['%H:%M', '%H:%M:%S']
MAX_SECTION = 20
MAX_WEEK = 30
CALENDAR_KINDS = list(CalendarEvent.Kind.values)
OCCURRENCE_KINDS = ['course', 'college', 'activity', 'appoint', 'custom', 'exam']
OVERVIEW_KINDS = list(OVERVIEW_SLOT_KINDS)


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
    total_weeks = serializers.IntegerField(help_text='Including exam weeks')
    exam_week_start = serializers.IntegerField(
        allow_null=True, help_text='First 考试周; null when the term has none (§8.4)')
    teaching_weeks = serializers.IntegerField(
        help_text='exam_week_start - 1 when set, else total_weeks')
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
    kind = serializers.ChoiceField(choices=OCCURRENCE_KINDS)
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
    role = serializers.CharField(
        allow_blank=True,
        help_text="'enrolled' | 'audit' | '' ('' for live sources, §8.2)")
    tag = serializers.CharField(allow_blank=True, help_text='The entry tag (§8.3)')
    modified = serializers.BooleanField(
        help_text='At least one override applied to this occurrence (§8.2)')


class SourceLegendSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class SourceSettingSerializer(SourceLegendSerializer):
    setting = serializers.CharField(
        allow_blank=True, help_text='The Settings boolean toggling the source')


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


class AgendaQuerySerializer(serializers.Serializer):
    """Query of ``agenda/``: ``from`` (default today) and ``days`` (default 7)."""

    # ``from`` is a keyword, so the field is declared through the namespace.
    locals()['from'] = serializers.DateField(
        required=False, help_text='First day (YYYY-MM-DD), default today')
    days = serializers.IntegerField(
        required=False, default=7, min_value=1,
        help_text=f'Number of days, default 7, capped at {AGENDA_MAX_DAYS}')


class AgendaDaySerializer(serializers.Serializer):
    """One date of the agenda, §6.5."""

    date = serializers.DateField()
    weekday = serializers.IntegerField()
    term = serializers.CharField(allow_null=True, help_text='Term code; null outside every term')
    week = serializers.IntegerField(allow_null=True)
    kind = serializers.ChoiceField(choices=CALENDAR_KINDS, allow_null=True)
    label = serializers.CharField(allow_null=True)
    occurrences = OccurrenceSerializer(many=True)


class AgendaSerializer(serializers.Serializer):
    """``AgendaOut`` of §6.5."""

    locals()['from'] = serializers.DateField()
    days = AgendaDaySerializer(many=True)
    sources = SourceLegendSerializer(many=True)


class OverviewSlotSerializer(serializers.Serializer):
    """One weekly slot of the term overview, §10."""

    key = serializers.CharField(help_text='Stable within the response')
    kind = serializers.ChoiceField(choices=OVERVIEW_KINDS)
    source = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    location = serializers.CharField(allow_blank=True)
    weekday = serializers.IntegerField(help_text='1=Mon..7=Sun')
    start = serializers.CharField(help_text='HH:MM')
    end = serializers.CharField(help_text='HH:MM')
    start_section = serializers.IntegerField(allow_null=True)
    end_section = serializers.IntegerField(allow_null=True)
    weeks = serializers.ListField(
        child=serializers.IntegerField(),
        help_text='Teaching weeks the slot runs, ascending')
    weeks_text = serializers.CharField(
        help_text="'第3周' | '1-16周' | '1-15周 单周' | '2-16周 双周' | '1-8,10-16周'")
    parity = serializers.ChoiceField(
        choices=TimetableEntry.Parity.choices,
        help_text='1 odd / 2 even when that pattern describes weeks, else 0')
    color_key = serializers.CharField(allow_blank=True)
    role = serializers.CharField(
        allow_blank=True, help_text="'enrolled' | 'audit' | '' ('' for 书院课)")
    tag = serializers.CharField(allow_blank=True, help_text='The entry tag (§8.3)')
    ref = serializers.DictField(
        child=serializers.IntegerField(allow_null=True),
        help_text='{entry_id} of a stored entry, {course_id} of a 书院课')


class OverviewExamSerializer(serializers.Serializer):
    """One exam of the term overview, §10."""

    title = serializers.CharField()
    date = serializers.DateField()
    start = serializers.CharField(help_text='HH:MM')
    end = serializers.CharField(help_text='HH:MM')
    location = serializers.CharField(allow_blank=True)
    week = serializers.IntegerField(
        allow_null=True, help_text='Teaching week; null outside 1..total_weeks')


class OverviewSerializer(serializers.Serializer):
    """``OverviewOut`` of §10."""

    term = TermSerializer()
    slots = OverviewSlotSerializer(many=True)
    exams = OverviewExamSerializer(many=True)


class EntryCatalogSerializer(serializers.ModelSerializer):
    """The catalog row an entry is linked to (``Entry.catalog``, §8.1)."""

    credits = serializers.FloatField(allow_null=True, read_only=True)

    class Meta:
        model = CourseCatalogEntry
        fields = ['id', 'course_code', 'name', 'class_no', 'teacher', 'credits',
                  'department', 'category', 'time_text', 'weeks_text', 'note']
        read_only_fields = fields


class EntryOverrideSerializer(serializers.ModelSerializer):
    """One per-week-range override of an entry (``Entry.overrides``, §8.2)."""

    fields = serializers.DictField(read_only=True)
    updated_at = serializers.DateTimeField(format=DATETIME_FORMAT, read_only=True)

    class Meta:
        model = TimetableEntryOverride
        fields = ['id', 'week_start', 'week_end', 'canceled', 'fields', 'updated_at']
        read_only_fields = fields


class EntryExamSerializer(serializers.ModelSerializer):
    """
    The exam of an entry (``Entry.exam``, §8.4): the first matching
    ``CourseExam``, else the entry's own imported exam with ``id: null``,
    ``method: ''``, the assumed window of its period and the note
    ``教务部统一考试时段``.
    """

    id = serializers.IntegerField(
        read_only=True, allow_null=True,
        help_text="CourseExam id; null for the entry's own imported exam")
    start = serializers.DateTimeField(format=DATETIME_FORMAT, read_only=True)
    end = serializers.DateTimeField(format=DATETIME_FORMAT, read_only=True)

    class Meta:
        model = CourseExam
        fields = ['id', 'start', 'end', 'room', 'method', 'note']
        read_only_fields = fields


class EntrySerializer(serializers.ModelSerializer):
    """
    Read shape of a stored entry. Pass ``context['exams']`` (``{entry id:
    [CourseExam]}`` from ``timetable.exams.exams_for_entries``) to serialize
    a list without one exam query per entry.
    """

    term = serializers.CharField(source='term.code', read_only=True)
    start_time = serializers.TimeField(format='%H:%M', read_only=True)
    end_time = serializers.TimeField(format='%H:%M', read_only=True)
    catalog = EntryCatalogSerializer(
        source='catalog_entry', read_only=True, allow_null=True)
    overrides = EntryOverrideSerializer(many=True, read_only=True)
    exam = serializers.SerializerMethodField()

    class Meta:
        model = TimetableEntry
        fields = [
            'id', 'term', 'source', 'name', 'course_code', 'class_no',
            'teacher', 'room', 'weekday', 'start_section', 'end_section',
            'start_time', 'end_time', 'week_start', 'week_end', 'parity',
            'note', 'hidden', 'color', 'role', 'category', 'tag',
            'catalog', 'overrides', 'exam',
        ]
        read_only_fields = fields

    def get_exam(self, entry) -> dict | None:
        exams = self.context.get('exams')
        if exams is None or entry.pk not in exams:
            exams = exams_for_entries(entry.term, [entry])
        matched = exams.get(entry.pk) or []
        if matched:
            return EntryExamSerializer(matched[0]).data
        window = entry_exam_window(entry)
        if window is None:
            return None
        own = SimpleNamespace(id=None, start=window[0], end=window[1],
                              room=entry.exam_room, method='', note=ENTRY_EXAM_NOTE)
        return EntryExamSerializer(own).data


class EntryInSerializer(serializers.Serializer):
    """
    Write shape of an entry. ``start_time``/``end_time`` may be omitted
    when sections are given (they are filled from the term's section table);
    ``start_section``/``end_section`` may be 0 when explicit times are given.
    ``catalog_id`` (a catalog row of the same term, ``null`` unlinks) is
    validated into ``catalog_entry``. Pass the target ``AcademicTerm`` as
    ``context['term']``.
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
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=NOTE_MAX_LENGTH)
    hidden = serializers.BooleanField(required=False)
    color = serializers.RegexField(
        r'^#[0-9a-fA-F]{6}$', required=False, allow_blank=True, max_length=7)
    role = serializers.ChoiceField(choices=TimetableEntry.Role.choices, required=False)
    category = serializers.ChoiceField(
        choices=TimetableEntry.Category.choices, required=False)
    tag = serializers.CharField(
        required=False, allow_blank=True, max_length=TAG_MAX_LENGTH)
    catalog_id = serializers.IntegerField(
        required=False, allow_null=True,
        help_text='Catalog row of the same term to link; null unlinks')

    _ENTRY_FIELDS = (
        'name', 'course_code', 'class_no', 'teacher', 'room', 'weekday',
        'start_section', 'end_section', 'start_time', 'end_time',
        'week_start', 'week_end', 'parity', 'note', 'hidden', 'color',
    )

    def validate_tag(self, value: str) -> str:
        return value.strip()

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
        if 'catalog_id' in attrs:
            catalog_id = attrs.pop('catalog_id')
            row = None
            if catalog_id is not None:
                if term is not None:
                    row = CourseCatalogEntry.objects.filter(
                        pk=catalog_id, term=term).first()
                if row is None:
                    raise serializers.ValidationError(
                        {'catalog_id': '课程目录中没有该学期的这门课'})
            attrs['catalog_entry'] = row
        return attrs


class EntryScopeSerializer(serializers.Serializer):
    """
    The scope part of ``PATCH entries/<id>/`` (§8.2): ``scope`` (default
    ``all``), ``week`` (required for ``single``/``following``, inside the
    entry's span — pass the entry as ``context['entry']``) and ``canceled``
    (single/following only). The remaining keys of the body are entry
    fields validated by ``EntryInSerializer``.
    """

    scope = serializers.ChoiceField(choices=list(SCOPES), required=False, default='all')
    week = serializers.IntegerField(required=False, allow_null=True)
    canceled = serializers.BooleanField(required=False, allow_null=True)

    def validate(self, attrs):
        scope = attrs.get('scope') or 'all'
        week = attrs.get('week')
        entry = self.context.get('entry')
        if scope == 'all':
            if attrs.get('canceled') is not None:
                raise serializers.ValidationError(
                    {'canceled': '整门课程不能标记停课，请隐藏或删除该条目'})
            attrs['week'] = None
            return attrs
        if week is None:
            raise serializers.ValidationError({'week': '按周修改时必须指定周次'})
        if entry is not None and not entry.contains_week(int(week)):
            raise serializers.ValidationError(
                {'week': f'周次必须在 {entry.week_start}–{entry.week_end} 之间'})
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
    exam_date = serializers.CharField(
        allow_blank=True, help_text="考试信息 date YYYY-MM-DD; '' when none")
    exam_period = serializers.CharField(
        allow_blank=True, help_text="'上午' | '下午' | '晚上' | ''")
    exam_room = serializers.CharField(allow_blank=True)


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
    """
    Write shape of ``TimetableSettings`` (the ICS token is not exposed).
    ``hidden_tags`` is deduplicated, trimmed and limited to 24 characters
    per tag (§8.3).
    """

    reminder_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    hidden_tags = serializers.ListField(
        child=serializers.CharField(max_length=TAG_MAX_LENGTH, allow_blank=True),
        required=False, max_length=200,
        help_text='Tags whose entries are hidden everywhere')

    class Meta:
        model = TimetableSettings
        fields = [
            'reminder_enabled', 'reminder_minutes', 'show_courses', 'show_college',
            'show_activities', 'show_appointments', 'show_exams', 'share_show_name',
            'hidden_tags',
        ]

    def validate_hidden_tags(self, value: list[str]) -> list[str]:
        tags: list[str] = []
        for tag in value:
            tag = tag.strip()
            if tag and tag not in tags:
                tags.append(tag)
        return tags


class SettingsOutSerializer(SettingsSerializer):
    """Read shape of the settings: the stored values plus the legend and tags."""

    sources = SourceSettingSerializer(
        many=True, read_only=True,
        help_text='Registered sources in config order with their toggle setting')
    tags = serializers.ListField(
        child=serializers.CharField(), read_only=True,
        help_text="Distinct tags of the person's entries, all terms, sorted")

    class Meta(SettingsSerializer.Meta):
        fields = SettingsSerializer.Meta.fields + ['sources', 'tags']


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
    """
    Read shape of a course catalog row for the entry form and the quick-add
    sheet (§6.3, §8.1). ``added`` reads ``context['added']`` — the ids of the
    rows the person already has an entry linked to in the term.
    """

    credits = serializers.FloatField(allow_null=True, read_only=True)
    slots = CatalogSlotSerializer(many=True, read_only=True)
    added = serializers.SerializerMethodField()

    class Meta:
        model = CourseCatalogEntry
        fields = ['id', 'course_code', 'name', 'class_no', 'teacher',
                  'credits', 'time_text', 'slots', 'department', 'category',
                  'audience', 'hours_per_week', 'weeks_text', 'note', 'added']
        read_only_fields = fields

    def get_added(self, row) -> bool:
        added = self.context.get('added')
        return bool(added) and row.pk in added


class CatalogAddSerializer(serializers.Serializer):
    """Body of ``POST catalog/<id>/add/`` (§8.1)."""

    role = serializers.ChoiceField(
        choices=TimetableEntry.Role.choices, required=False,
        default=TimetableEntry.Role.AUDIT)
    slots = serializers.ListField(
        child=serializers.IntegerField(min_value=0), required=False,
        help_text='Indices into the catalog row slots; default all')
    term = serializers.CharField(required=False, allow_blank=True, max_length=16)


class ShareAssetsSerializer(serializers.Serializer):
    """``GET share/assets/`` (§8.5)."""

    miniapp_qrcode = serializers.URLField(
        allow_null=True,
        help_text='Absolute URL of the mini-program code image, or null')
    official_qrcode = serializers.URLField(
        allow_null=True,
        help_text='Absolute URL of the official-account QR code, or null')
    slogan = serializers.CharField()
