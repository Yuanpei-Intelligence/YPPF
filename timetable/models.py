"""
Models of the timetable app: academic terms, stored timetable entries,
import logs, per-person settings (``timetable/README.md`` §4.1), subscribe
quotas and reminder logs (§6.1) and the course catalog (§6.3).

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
    'ImportLog',
    'TimetableSettings',
    'SubscribeQuota',
    'ReminderLog',
    'CourseCatalogEntry',
]


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
    total_weeks = models.PositiveSmallIntegerField('总周数', default=16)
    section_times = models.JSONField(
        '节次时间表', default=default_section_times,
        help_text='{"1": ["08:00", "08:50"], ...}')
    is_active = models.BooleanField('启用', default=True)

    def __str__(self) -> str:
        return f'{self.name} ({self.code})'

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
    """

    class Source(models.TextChoices):
        PORTAL = 'portal', '门户导入'
        PASTE = 'paste', '粘贴导入'
        MANUAL = 'manual', '手动添加'

    class Parity(models.IntegerChoices):
        ALL = 0, '每周'
        ODD = 1, '单周'
        EVEN = 2, '双周'

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

    note = models.CharField('备注', max_length=200, blank=True)
    raw_text = models.TextField('原始文本', blank=True)
    hidden = models.BooleanField('隐藏', default=False)
    color = models.CharField('颜色', max_length=7, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    def __str__(self) -> str:
        return f'{self.name} 周{self.weekday} {self.start_section}-{self.end_section}节'

    @property
    def kind(self) -> str:
        """Occurrence kind: ``'custom'`` for manual entries, else ``'course'``."""
        return 'custom' if self.source == self.Source.MANUAL else 'course'

    def is_manual(self) -> bool:
        return self.source == self.Source.MANUAL

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
    show_college = models.BooleanField('显示书院课', default=True)
    show_activities = models.BooleanField('显示活动', default=True)
    show_appointments = models.BooleanField('显示预约', default=True)
    share_show_name = models.BooleanField('海报显示姓名', default=True)

    def __str__(self) -> str:
        return f'{self.person} 的课表设置'

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
