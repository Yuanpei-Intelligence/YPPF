"""
Source of the term's exam schedule (``timetable/README.md`` §8.4): one
occurrence per ``CourseExam`` matched by the person's visible course
entries. Registered in ``config.json → timetable.sources``; honours
``settings.show_exams`` and the hidden tags of §8.3.
"""
from __future__ import annotations

from timetable.exams import match_exams
from timetable.models import CourseExam, TimetableEntry
from timetable.sources.base import Occurrence, occurrence_sort_key, week_span

__all__ = ['ExamSource']


class ExamSource:
    """
    Exams of the person's non-hidden ``category='course'`` entries, matched
    by ``(course_code, class_no)`` (catalog values when linked), then by a
    unique course code, then by exact name (``timetable.exams``). Each exam
    is emitted once even when several entries (slots) match. Term-based:
    date-span queries go through the default
    ``timetable.sources.base.term_occurrences_between``.
    """

    key = 'exam'
    label = '考试'
    setting = 'show_exams'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_exams:
            return []
        if week_from > week_to:
            return []
        span_start, span_end = week_span(term, week_from, week_to)
        exams = list(
            CourseExam.objects
            .filter(term=term, start__gte=span_start, start__lt=span_end)
            .order_by('start', 'id'))
        if not exams:
            return []
        entries = list(
            TimetableEntry.objects
            .filter(person=person, term=term, hidden=False,
                    category=TimetableEntry.Category.COURSE)
            .select_related('catalog_entry').order_by('id'))
        hidden_tags = settings.hidden_tag_set() if settings is not None else set()
        if hidden_tags:
            entries = [entry for entry in entries if entry.tag not in hidden_tags]
        result = [self._occurrence(exam, entry, term)
                  for exam, entry in match_exams(entries, exams)]
        result.sort(key=occurrence_sort_key)
        return result

    @staticmethod
    def _occurrence(exam: CourseExam, entry: TimetableEntry, term) -> Occurrence:
        on = exam.start.date()
        return Occurrence(
            id=f'exam:{exam.pk}:{on.isoformat()}',
            source='exam',
            kind='exam',
            title=f'{exam.name} 考试',
            subtitle=exam.method or exam.teacher,
            location=exam.room,
            start=exam.start,
            end=exam.end,
            date=on,
            week=term.week_of(on),
            weekday=on.isoweekday(),
            start_section=None,
            end_section=None,
            color_key=exam.name,
            status='',
            ref={'exam_id': exam.pk, 'entry_id': entry.pk},
            role='',
        )
