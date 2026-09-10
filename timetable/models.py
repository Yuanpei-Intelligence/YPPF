"""
Models of the timetable app: academic terms, stored timetable entries and
their per-week overrides, import logs, per-person settings
(``timetable/README.md`` §4.1, §8.2, §8.3), subscribe quotas and reminder
logs (§6.1), the course catalog (§6.3) and the exam schedule (§8.4).

Stored data is per ``(person, term)``. Entries of one import source are
replaced as a set by ``timetable.services.upsert_entries``; other sources and
other terms are never touched by an import.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from django.db import models
from django.db.models import Q

from utils.models.semester import Semester
from generic.models import User
from app.models import NaturalPerson

__all__ = [
    'default_section_times',
    'AcademicTerm',
    'TimetableEntry',
    'TimetableEntryOverride',
    'OVERRIDE_FIELD_KEYS',
    'TAG_MAX_LENGTH',
    'ImportLog',
    'TimetableSettings',
    'SubscribeQuota',
    'ReminderLog',
    'CourseCatalogEntry',
    'CourseExam',
]

# Keys a ``TimetableEntryOverride.fields`` JSON may carry (README §8.2);
# times are ``'HH:MM'`` strings. Order is the display order of the API.
OVERRIDE_FIELD_KEYS = (
    'name', 'teacher', 'room', 'weekday', 'start_section', 'end_section',
    'start_time', 'end_time', 'note', 'tag', 'color',
)
# Longest tag of an entry and longest entry of ``TimetableSettings.hidden_tags``.
TAG_MAX_LENGTH = 24


def default_section_times() -> dict[str, list[str]]:
    """PKU 校本部 50-minute section table (verified against xmcp/pku-syllabus)."""
    return {
        '1': ['08:00', '08:50'],
        '2': ['09:00', '09:50'],
        '3': ['10:10', '11:00'],
        '4': ['11:10', '12:00'],
        '5': ['13:00', '13:50'],
        '6': ['14:00', '14:50'],
        '7': ['15:10', '16:00'],
        '8': ['16:10', '17:00'],
        '9': ['17:10', '18:00'],
        '10': ['18:40', '19:30'],
        '11': ['19:40', '20:30'],
        '12': ['20:40', '21:30'],
    }


_TERM_CODE_RE = re.compile(r'^(\d{2}|\d{4})-(\d{2}|\d{4})-(\d)$')


class AcademicTerm(models.Model):
    """
    A teaching term of the university timetable.

    ``code`` is the portal ``xndxq`` value, e.g. ``'26-27-1'`` (1 秋, 2 春,
    3 夏). Week numbers are counted from ``week1_monday``; ``week_of`` may
    return values below 1 or above ``total_weeks`` for dates outside the term.
    """

    class Meta:
        verbose_name = '课表学期'
        verbose_name_plural = verbose_name
        ordering = ['-week1_monday']

    code = models.CharField('学期代码', max_length=16, unique=True)
    name = models.CharField('学期名称', max_length=32)
    week1_monday = models.DateField('第一教学周周一')
    total_weeks = models.PositiveSmallIntegerField(
        '总周数', default=16, help_text='含考试周')
    exam_week_start = models.PositiveSmallIntegerField(
        '考试周起始周', null=True, blank=True,
        help_text='从该周起为考试周；留空表示没有考试周')
    section_times = models.JSONField(
        '节次时间表', default=default_section_times,
        help_text='{"1": ["08:00", "08:50"], ...}')
    is_active = models.BooleanField('启用', default=True)

    def __str__(self) -> str:
        return f'{self.name} ({self.code})'

    @property
    def teaching_weeks(self) -> int:
        """
        Number of teaching weeks: ``exam_week_start - 1`` when exam weeks
        are configured (never below 1 nor above ``total_weeks``), otherwise
        ``total_weeks`` (README §8.4).
        """
        total = max(int(self.total_weeks), 1)
        if self.exam_week_start is None:
            return total
        return max(1, min(int(self.exam_week_start) - 1, total))

    def is_exam_week(self, week: int) -> bool:
        """Whether teaching week ``week`` is an exam week of this term."""
        return (self.exam_week_start is not None
                and int(self.exam_week_start) <= week <= int(self.total_weeks))

    @classmethod
    def current(cls, on: date | None = None) -> 'AcademicTerm | None':
        """
        The latest active term whose ``week1_monday`` is on or before ``on``
        (today by default); ``None`` when no such term exists. The end of a
        term is not considered, so during a holiday the previous term is
        still "current".
        """
        if on is None:
            on = date.today()
        return (cls.objects.filter(is_active=True, week1_monday__lte=on)
                .order_by('-week1_monday').first())

    @classmethod
    def upcoming(cls, on: date | None = None) -> 'AcademicTerm | None':
        """The earliest active term starting after ``on``; ``None`` if none."""
        if on is None:
            on = date.today()
        return (cls.objects.filter(is_active=True, week1_monday__gt=on)
                .order_by('week1_monday').first())

    def week_of(self, on: date) -> int:
        """1-based teaching week of a date; may be < 1 or > ``total_weeks``."""
        return (on - self.week1_monday).days // 7 + 1

    def date_of(self, week: int, weekday: int) -> date:
        """Date of ``weekday`` (1=Mon..7=Sun) in teaching week ``week``."""
        return self.week1_monday + timedelta(days=7 * (week - 1) + weekday - 1)

    def week_dates(self, week: int) -> list[date]:
        """The seven dates (Mon..Sun) of teaching week ``week``."""
        return [self.date_of(week, weekday) for weekday in range(1, 8)]

    def end_date(self) -> date:
        """Sunday of the last teaching week."""
        return self.date_of(max(int(self.total_weeks), 1), 7)

    def covers(self, on: date) -> bool:
        """Whether ``on`` lies in the teaching span ``week1_monday..end_date()``."""
        return self.week1_monday <= on <= self.end_date()

    def contains_week(self, week: int) -> bool:
        """Whether ``week`` is a teaching week of this term."""
        return 1 <= week <= self.total_weeks

    def clamp_week(self, week: int) -> int:
        """Clamp a week number into ``1..total_weeks``."""
        return max(1, min(int(week), max(int(self.total_weeks), 1)))

    def yppf_year_semester(self) -> tuple[int, Semester] | None:
        """
        Map the term code to the YPPF ``(year, Semester)`` pair used by
        ``app.Course`` / ``app.Activity``: ``'26-27-1'`` → ``(2026, FALL)``,
        ``'26-27-2'`` → ``(2026, SPRING)``; summer terms and malformed codes
        give ``None``.
        """
        match = _TERM_CODE_RE.match(self.code or '')
        if match is None:
            return None
        year = int(match.group(1))
        if year < 100:
            year += 2000
        suffix = match.group(3)
        if suffix == '1':
            return year, Semester.FALL
        if suffix == '2':
            return year, Semester.SPRING
        return None

    def section_time(self, section: int) -> tuple[time, time] | None:
        """
        ``(start, end)`` of a section from ``section_times``. Sections beyond
        the table are clamped to its first/last row so an unusual 13th
        section still gets a time; a malformed table gives ``None``.
        """
        table = self.section_times if isinstance(self.section_times, dict) else {}
        numbers = sorted(int(key) for key in table if str(key).isdigit())
        if not numbers:
            return None
        section = max(numbers[0], min(int(section), numbers[-1]))
        row = table.get(str(section))
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            return None
        try:
            return _parse_hhmm(row[0]), _parse_hhmm(row[1])
        except ValueError:
            return None


def _parse_hhmm(value: str) -> time:
    # Accept 'HH:MM' and 'HH:MM:SS'.
    parts = str(value).strip().split(':')
    if len(parts) not in (2, 3):
        raise ValueError(value)
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 0)


class TimetableEntry(models.Model):
    """
    One weekly lesson of a person in a term, as imported or entered.

    ``external_key`` is the sha1 of the normalised identity fields for
    portal/paste imports and a uuid4 hex for manual entries; it is what
    re-imports upsert on. ``start_section``/``end_section`` may be 0 for a
    manual entry with explicit times.

    ``catalog_entry``, ``role``, ``category`` and ``tag`` (README §8.1, §8.3)
    are the student's own annotations: a re-import keeps them, like
    ``hidden``/``color`` and the ``TimetableEntryOverride`` rows (§8.2).
    """

    class Source(models.TextChoices):
        PORTAL = 'portal', '门户导入'
        PASTE = 'paste', '粘贴导入'
        MANUAL = 'manual', '手动添加'

    class Parity(models.IntegerChoices):
        ALL = 0, '每周'
        ODD = 1, '单周'
        EVEN = 2, '双周'

    class Role(models.TextChoices):
        ENROLLED = 'enrolled', '已选'
        AUDIT = 'audit', '旁听'

    class Category(models.TextChoices):
        COURSE = 'course', '课程'
        EXAM = 'exam', '考试'
        OTHER = 'other', '其它'

    # Occurrence ``kind`` by category (README §8.1).
    KIND_BY_CATEGORY = {'course': 'course', 'exam': 'exam', 'other': 'custom'}

    class Meta:
        verbose_name = '课表条目'
        verbose_name_plural = verbose_name
        ordering = ['weekday', 'start_section', 'start_time', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['person', 'term', 'source', 'external_key'],
                name='timetable_entry_unique_key'),
            models.CheckConstraint(
                condition=Q(weekday__gte=1, weekday__lte=7),
                name='timetable_entry_weekday_range'),
            models.CheckConstraint(
                condition=Q(start_section__lte=models.F('end_section')),
                name='timetable_entry_section_order'),
            models.CheckConstraint(
                condition=Q(week_start__lte=models.F('week_end')),
                name='timetable_entry_week_order'),
        ]

    person = models.ForeignKey(
        NaturalPerson, on_delete=models.CASCADE,
        related_name='timetable_entries', verbose_name='学生')
    term = models.ForeignKey(
        AcademicTerm, on_delete=models.PROTECT,
        related_name='entries', verbose_name='学期')
    source = models.CharField('来源', max_length=16, choices=Source.choices)
    external_key = models.CharField('外部键', max_length=64)
    catalog_entry = models.ForeignKey(
        'CourseCatalogEntry', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='timetable_entries', verbose_name='课程目录')
    role = models.CharField(
        '身份', max_length=16, choices=Role.choices, default=Role.ENROLLED)
    category = models.CharField(
        '类别', max_length=16, choices=Category.choices, default=Category.COURSE)
    tag = models.CharField('标签', max_length=TAG_MAX_LENGTH, blank=True)

    name = models.CharField('课程名', max_length=100)
    course_code = models.CharField('课程号', max_length=32, blank=True)
    class_no = models.CharField('班号', max_length=16, blank=True)
    teacher = models.CharField('教师', max_length=100, blank=True)
    room = models.CharField('教室', max_length=100, blank=True)

    weekday = models.SmallIntegerField('星期', help_text='1=周一 … 7=周日')
    start_section = models.SmallIntegerField('起始节')
    end_section = models.SmallIntegerField('结束节')
    start_time = models.TimeField('开始时间')
    end_time = models.TimeField('结束时间')
    week_start = models.SmallIntegerField('起始周')
    week_end = models.SmallIntegerField('结束周')
    parity = models.SmallIntegerField(
        '单双周', choices=Parity.choices, default=Parity.ALL)

    note = models.TextField('备注', blank=True)
    raw_text = models.TextField('原始文本', blank=True)
    hidden = models.BooleanField('隐藏', default=False)
    color = models.CharField('颜色', max_length=7, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    def __str__(self) -> str:
        return f'{self.name} 周{self.weekday} {self.start_section}-{self.end_section}节'

    @property
    def kind(self) -> str:
        """
        Occurrence kind derived from ``category`` (README §8.1): ``'course'``,
        ``'exam'`` or ``'custom'`` (category ``other``).
        """
        return self.KIND_BY_CATEGORY.get(str(self.category), 'course')

    def is_manual(self) -> bool:
        return self.source == self.Source.MANUAL

    def contains_week(self, week: int) -> bool:
        """Whether ``week`` lies in the entry's own ``week_start..week_end``."""
        return self.week_start <= week <= self.week_end

    def occurs_in_week(self, week: int) -> bool:
        """Whether the entry has a lesson in teaching week ``week``."""
        if not self.week_start <= week <= self.week_end:
            return False
        if self.parity == self.Parity.ODD:
            return week % 2 == 1
        if self.parity == self.Parity.EVEN:
            return week % 2 == 0
        return True

    def start_at(self, on: date) -> datetime:
        return datetime.combine(on, self.start_time)

    def end_at(self, on: date) -> datetime:
        return datetime.combine(on, self.end_time)

    @staticmethod
    def new_manual_key() -> str:
        """External key of a manual entry."""
        return uuid4().hex


# Module-level aliases for SPECTACULAR_SETTINGS['ENUM_NAME_OVERRIDES'] (the
# override loader imports ``module.attribute`` paths only).
ENTRY_ROLE_CHOICES = TimetableEntry.Role.choices
ENTRY_CATEGORY_CHOICES = TimetableEntry.Category.choices


class TimetableEntryOverride(models.Model):
    """
    A per-week-range modification of one entry (README §8.2): ``fields``
    holds only the overridden keys (``OVERRIDE_FIELD_KEYS``; a present key
    is the effective value, an absent key means "unchanged"), ``canceled``
    drops the occurrences of the range. ``week_start``/``week_end`` of
    ``None`` follow the entry's own first/last week, so a re-import that
    moves the entry's span keeps "this and following" edits meaningful.

    Overlapping ranges are resolved by ``timetable.overrides`` — descending
    range width, then ascending id, so a narrower or newer override wins
    for every key including ``canceled``.
    """

    class Meta:
        verbose_name = '课表条目修改'
        verbose_name_plural = verbose_name
        ordering = ['id']

    entry = models.ForeignKey(
        TimetableEntry, on_delete=models.CASCADE,
        related_name='overrides', verbose_name='条目')
    week_start = models.SmallIntegerField(
        '起始周', null=True, blank=True, help_text='留空 = 条目的起始周')
    week_end = models.SmallIntegerField(
        '结束周', null=True, blank=True, help_text='留空 = 条目的结束周')
    canceled = models.BooleanField('停课', default=False)
    fields = models.JSONField('修改的字段', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    def __str__(self) -> str:
        span = f'{self.week_start or "*"}-{self.week_end or "*"}'
        state = '停课' if self.canceled else ','.join(sorted(self.fields or {}))
        return f'{self.entry_id} 周次{span} {state}'

    def bounds(self, entry: TimetableEntry | None = None) -> tuple[int, int]:
        """Effective ``(first, last)`` week, open bounds taken from ``entry``."""
        if entry is None:
            entry = self.entry
        first = entry.week_start if self.week_start is None else int(self.week_start)
        last = entry.week_end if self.week_end is None else int(self.week_end)
        return first, last

    def applies_to(self, week: int, entry: TimetableEntry | None = None) -> bool:
        """Whether the override covers teaching week ``week``."""
        first, last = self.bounds(entry)
        return first <= week <= last


class ImportLog(models.Model):
    """Audit record of one timetable import attempt."""

    class Status(models.TextChoices):
        OK = 'ok', '成功'
        FAILED = 'failed', '失败'

    class Meta:
        verbose_name = '课表导入记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at', '-id']

    person = models.ForeignKey(
        NaturalPerson, on_delete=models.CASCADE,
        related_name='timetable_import_logs', verbose_name='学生')
    term = models.ForeignKey(
        AcademicTerm, on_delete=models.CASCADE,
        related_name='import_logs', verbose_name='学期')
    source = models.CharField(
        '来源', max_length=16, choices=TimetableEntry.Source.choices)
    status = models.CharField('结果', max_length=8, choices=Status.choices)
    entries_count = models.PositiveIntegerField('条目数', default=0)
    message = models.TextField('信息', blank=True)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    def __str__(self) -> str:
        return f'{self.person} {self.term.code} {self.source} {self.status}'


class TimetableSettings(models.Model):
    """Per-person timetable preferences and the private ICS feed token."""

    class Meta:
        verbose_name = '课表设置'
        verbose_name_plural = verbose_name

    person = models.OneToOneField(
        NaturalPerson, on_delete=models.CASCADE,
        related_name='timetable_settings', verbose_name='学生')
    ics_token = models.UUIDField('ICS 令牌', default=uuid4, unique=True)
    reminder_enabled = models.BooleanField('上课提醒', default=False)
    reminder_minutes = models.PositiveSmallIntegerField('提前分钟数', default=20)
    show_courses = models.BooleanField('显示学校课表', default=True)
    show_college = models.BooleanField('显示书院课', default=True)
    show_activities = models.BooleanField('显示活动', default=True)
    show_appointments = models.BooleanField('显示预约', default=True)
    show_exams = models.BooleanField('显示考试', default=True)
    hidden_tags = models.JSONField(
        '隐藏的标签', default=list, blank=True,
        help_text='带这些标签的条目不在课表中显示')
    share_show_name = models.BooleanField('海报显示姓名', default=True)

    def __str__(self) -> str:
        return f'{self.person} 的课表设置'

    def hidden_tag_set(self) -> set[str]:
        """The hidden tags as a set of strings (a malformed value is empty)."""
        if not isinstance(self.hidden_tags, list):
            return set()
        return {str(tag) for tag in self.hidden_tags if str(tag)}

    def rotate_ics_token(self) -> None:
        """Replace the ICS token, invalidating the previous feed URL."""
        self.ics_token = uuid4()
        self.save(update_fields=['ics_token'])


class SubscribeQuota(models.Model):
    """
    Accepted-but-unused WeChat subscribe-message grants of a user, per
    template key (``timetable/README.md`` §6.1).

    The mini-program posts one grant for every ``accept`` returned by
    ``wx.requestSubscribeMessage``; each subscribe message sent consumes
    one. ``count`` is capped at ``timetable.subscribe_quota_cap`` when
    granting and is only changed through ``timetable.reminders``.
    """

    class Meta:
        verbose_name = '订阅消息配额'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'template_key'],
                name='timetable_subscribe_quota_unique'),
        ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='subscribe_quotas', verbose_name='用户')
    template_key = models.CharField('模板键', max_length=32)
    count = models.PositiveIntegerField('剩余次数', default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    def __str__(self) -> str:
        return f'{self.user.username} {self.template_key} x{self.count}'


class ReminderLog(models.Model):
    """
    One row per ``(person, occurrence)`` ever reminded, whatever the
    outcome, so a reminder is never sent twice. ``scheduled_for`` is the
    moment the reminder was due (class start minus the person's
    ``reminder_minutes``); ``sent_at`` is when it was actually handled and
    ``detail`` records why a channel was (not) used.
    """

    class Channel(models.TextChoices):
        SUBSCRIBE = 'subscribe', '订阅消息'
        NOTIFICATION = 'notification', '站内通知'
        SKIPPED = 'skipped', '未发送'

    class Meta:
        verbose_name = '上课提醒记录'
        verbose_name_plural = verbose_name
        ordering = ['-scheduled_for', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['person', 'occurrence_id'],
                name='timetable_reminder_log_unique'),
        ]

    person = models.ForeignKey(
        NaturalPerson, on_delete=models.CASCADE,
        related_name='reminder_logs', verbose_name='学生')
    occurrence_id = models.CharField('事件标识', max_length=128)
    channel = models.CharField('渠道', max_length=16, choices=Channel.choices)
    scheduled_for = models.DateTimeField('计划提醒时间')
    sent_at = models.DateTimeField('处理时间', auto_now_add=True)
    detail = models.CharField('详情', max_length=128, blank=True)

    def __str__(self) -> str:
        return f'{self.person} {self.occurrence_id} {self.channel}'


class CourseCatalogEntry(models.Model):
    """
    One class (课程号 + 班号) of the university course catalog in a term,
    imported from the PKU-Course-Crawler workbook by the
    ``import_course_catalog`` command (``timetable/README.md`` §6.3).

    ``slots`` is the best-effort parse of ``weeks_text`` + ``time_text``
    into ``LessonBlock``-like dicts (``weekday``, ``start_section``,
    ``end_section``, ``week_start``, ``week_end``, ``parity``, ``room``)
    used by the mini-program to prefill one manual entry per slot.
    """

    class Meta:
        verbose_name = '课程目录'
        verbose_name_plural = verbose_name
        ordering = ['course_code', 'class_no', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['term', 'course_code', 'class_no'],
                name='timetable_catalog_entry_unique'),
        ]

    term = models.ForeignKey(
        AcademicTerm, on_delete=models.CASCADE,
        related_name='catalog_entries', verbose_name='学期')
    department = models.CharField('院系', max_length=64, blank=True)
    course_code = models.CharField('课程号', max_length=32)
    name = models.CharField('课程名', max_length=80)
    name_en = models.CharField('课程英文名', max_length=160, blank=True)
    class_no = models.CharField('班号', max_length=8, blank=True)
    audience = models.CharField('修读对象', max_length=32, blank=True)
    category = models.CharField('课程类别', max_length=32, blank=True)
    credits = models.DecimalField(
        '参考学分', max_digits=4, decimal_places=1, null=True, blank=True)
    hours_per_week = models.CharField('周学时', max_length=16, blank=True)
    total_hours = models.CharField('总学时', max_length=16, blank=True)
    teacher = models.CharField('授课教师', max_length=80, blank=True)
    weeks_text = models.CharField('起止周', max_length=64, blank=True)
    time_text = models.CharField('上课时间', max_length=200, blank=True)
    note = models.CharField('备注', max_length=200, blank=True)
    slots = models.JSONField('时段', default=list, blank=True)

    def __str__(self) -> str:
        return f'{self.course_code}-{self.class_no} {self.name} ({self.term.code})'


class CourseExam(models.Model):
    """
    One exam sitting of the term's exam schedule (README §8.4), imported by
    ``import_exam_schedule`` and matched to the person's course entries by
    ``timetable.sources.exam.ExamSource``. ``raw_time`` keeps the source
    cell so a parsing problem can be traced.
    """

    class Meta:
        verbose_name = '考试安排'
        verbose_name_plural = verbose_name
        ordering = ['start', 'course_code', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['term', 'course_code', 'class_no', 'start'],
                name='timetable_course_exam_unique'),
        ]

    term = models.ForeignKey(
        AcademicTerm, on_delete=models.CASCADE,
        related_name='exams', verbose_name='学期')
    course_code = models.CharField('课程号', max_length=32)
    class_no = models.CharField('班号', max_length=8, blank=True)
    name = models.CharField('课程名', max_length=100)
    teacher = models.CharField('教师', max_length=80, blank=True)
    start = models.DateTimeField('开始时间')
    end = models.DateTimeField('结束时间')
    room = models.CharField('考场', max_length=100, blank=True)
    method = models.CharField('考试方式', max_length=32, blank=True)
    note = models.CharField('备注', max_length=200, blank=True)
    raw_time = models.CharField('原始时间文本', max_length=64, blank=True)

    def __str__(self) -> str:
        return f'{self.name} {self.start:%Y-%m-%d %H:%M} ({self.term.code})'
