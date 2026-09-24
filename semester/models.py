from datetime import date

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


__all__ = ['SemesterType', 'Semester', 'CalendarEvent']


class SemesterType(models.Model):
    class Meta:
        verbose_name = '学期类型'
        verbose_name_plural = verbose_name

    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Semester(models.Model):
    '''学期

    不同的学期时间不应重叠

    Attributes:
        year(int): 学年的起始年份，如2019-2020学年为2019
        type(SemesterType): 学期类型
        start_date(date): 开学日期
        end_date(date): 放假日期
    '''
    class Meta:
        verbose_name = '学期'
        verbose_name_plural = verbose_name
        unique_together = ['year', 'type']

    year = models.IntegerField('学年', help_text='学年的起始年份，如2019-2020学年为2019')
    type = models.ForeignKey(SemesterType, on_delete=models.CASCADE)
    start_date = models.DateField('开学日期')
    end_date = models.DateField('放假日期')


class CalendarEvent(models.Model):
    '''校历事件

    One entry of the university calendar (校历), global and keyed by date:
    a holiday, an exam period, a 调休 swap day or a plain annotation covering
    the inclusive range ``start_date..end_date``. Rows are transcribed from
    the published 校历 (``timetable`` command ``import_academic_calendar``)
    and edited in admin; read them through ``semester.calendar``, never
    hardcode dates.

    Attributes:
        kind(Kind): holiday/exam = 全校停课; swap = 按 follows_weekday 的课表上课;
            info = 仅标注（公休但课程照常、运动会等）
        start_date(date), end_date(date): 起止日期，含当日
        name(str): 显示给用户的名称
        follows_weekday(int | None): 1=周一 … 7=周日，仅 swap 填写
        note(str): 备注
    '''

    class Kind(models.TextChoices):
        HOLIDAY = 'holiday', '放假停课'
        EXAM = 'exam', '停课复习考试'
        SWAP = 'swap', '调休'
        INFO = 'info', '说明'

    class Meta:
        verbose_name = '校历事件'
        verbose_name_plural = verbose_name
        ordering = ['start_date', 'id']
        constraints = [
            models.CheckConstraint(
                condition=Q(start_date__lte=models.F('end_date')),
                name='semester_calendar_event_date_order'),
            models.CheckConstraint(
                condition=(Q(follows_weekday__isnull=True)
                           | Q(follows_weekday__gte=1, follows_weekday__lte=7)),
                name='semester_calendar_event_weekday_range'),
        ]

    kind = models.CharField('类型', max_length=16, choices=Kind.choices)
    start_date = models.DateField('开始日期')
    end_date = models.DateField('结束日期', help_text='含当日')
    name = models.CharField('名称', max_length=64)
    follows_weekday = models.PositiveSmallIntegerField(
        '按星期几的课表上课', null=True, blank=True,
        help_text='仅调休填写：1=周一 … 7=周日')
    note = models.CharField('备注', max_length=200, blank=True)

    def __str__(self) -> str:
        span = (str(self.start_date) if self.start_date == self.end_date
                else f'{self.start_date}..{self.end_date}')
        return f'{self.get_kind_display()} {span} {self.name}'

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if (self.start_date is not None and self.end_date is not None
                and self.end_date < self.start_date):
            errors['end_date'] = '结束日期不能早于开始日期。'
        if self.kind == self.Kind.SWAP:
            if self.follows_weekday is None:
                errors['follows_weekday'] = '调休需要指定按星期几的课表上课。'
        elif self.follows_weekday is not None:
            errors['follows_weekday'] = '只有调休可以指定按星期几的课表上课。'
        if (self.follows_weekday is not None
                and not 1 <= int(self.follows_weekday) <= 7):
            errors['follows_weekday'] = '星期取值须在 1（周一）到 7（周日）之间。'
        if errors:
            raise ValidationError(errors)

    @property
    def suspends_classes(self) -> bool:
        '''Whether the event cancels classes (holiday or exam period).'''
        return self.kind in (self.Kind.HOLIDAY, self.Kind.EXAM)

    def covers(self, on: date) -> bool:
        '''Whether ``on`` lies in the event's inclusive date range.'''
        return self.start_date <= on <= self.end_date
