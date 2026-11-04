"""
Grade records fetched from the PKU portal. Contract: ``timetable/README.md``
§6.2.

Rows exist only for students whose binding carries ``consent_grades``; a
sync without consent shows the live data and stores nothing, and revoking
the consent deletes every stored row (``academic_record.receivers``).
"""
from __future__ import annotations

from django.db import models

from app.models import NaturalPerson

__all__ = ['GradeRecord']


class GradeRecord(models.Model):
    """
    One course grade of a person in one term, as last fetched.

    ``score`` keeps the portal text (``'85'``, ``'P'``, ``'合格'``, ``'W'``);
    ``score_numeric`` is its numeric value when it has one. ``credits`` and
    ``gpa`` are ``None`` when the portal gave no usable number. ``raw`` holds
    the portal fields that have no column of their own; it is personal data
    and is never rendered by the API or the admin.
    """

    class Meta:
        verbose_name = '成绩记录'
        verbose_name_plural = verbose_name
        ordering = ['-term_code', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['person', 'term_code', 'course_code', 'name'],
                name='academic_record_grade_unique_key'),
        ]

    person = models.ForeignKey(
        NaturalPerson, on_delete=models.CASCADE,
        related_name='grade_records', verbose_name='学生')
    term_code = models.CharField(
        '学期代码', max_length=16, help_text='门户 xnd-xq，如 25-26-1')
    course_code = models.CharField('课程号', max_length=32, blank=True)
    class_no = models.CharField('班号', max_length=8, blank=True)
    name = models.CharField('课程名', max_length=80)
    course_type = models.CharField('课程类别', max_length=32, blank=True)
    credits = models.DecimalField(
        '学分', max_digits=4, decimal_places=1, null=True, blank=True)
    score = models.CharField('成绩', max_length=16, blank=True)
    score_numeric = models.FloatField('成绩数值', null=True, blank=True)
    gpa = models.FloatField('绩点', null=True, blank=True)
    raw = models.JSONField('原始数据', default=dict, blank=True)
    fetched_at = models.DateTimeField('获取时间')

    def __str__(self) -> str:
        return f'{self.term_code} {self.name}'
