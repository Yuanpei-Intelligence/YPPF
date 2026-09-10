"""
Source of the term's exams (``timetable/README.md`` §8.4): one occurrence
per ``CourseExam`` matched by the person's visible course entries, plus one
per course whose own imported 考试信息 (``TimetableEntry.exam_date``) no
``CourseExam`` covers. Registered in ``config.json → timetable.sources``;
honours ``settings.show_exams`` and the hidden tags of §8.3.
"""
from __future__ import annotations

from datetime import date

from timetable.exams import ENTRY_EXAM_NOTE, ExamIndex, entry_exam_window, match_exams
from timetable.models import CourseExam, TimetableEntry
from timetable.sources.base import Occurrence, occurrence_sort_key, week_span

__all__ = ['ExamSource']


class ExamSource:
    """
    Exams of the person's non-hidden ``category='course'`` entries.

    - Scheduled exams: ``CourseExam`` rows matched by ``(course_code,
      class_no)`` (catalog values when linked), then by a unique course
      code, then by exact name (``timetable.exams``). Each exam is emitted
      once even when several entries (slots) match.
    - The course's own exam: entries with an ``exam_date`` in the span whose
      ``(name, exam_date)`` no entry matching a ``CourseExam`` of the term
      (at any date) shares give one occurrence per ``(name, exam_date)``, in
      the assumed window of the period, with the note that the time is
      approximate.

    Term-based: date-span queries go through the default
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
        entries = TimetableEntry.objects.filter(
            person=person, term=term, hidden=False,
            category=TimetableEntry.Category.COURSE)
        if not exams:
            # Only entries with their own exam in the span can contribute.
            entries = entries.filter(exam_date__gte=span_start.date(),
                                     exam_date__lt=span_end.date())
        entries = list(entries.select_related('catalog_entry').order_by('id'))
        hidden_tags = settings.hidden_tag_set() if settings is not None else set()
        if hidden_tags:
            entries = [entry for entry in entries if entry.tag not in hidden_tags]
        result = [self._occurrence(exam, entry, term)
                  for exam, entry in match_exams(entries, exams)]
        result.extend(self._own_exams(entries, term, span_start.date(), span_end.date()))
        result.sort(key=occurrence_sort_key)
        return result

    def _own_exams(self, entries: list[TimetableEntry], term, first_day: date,
                   end_day: date) -> list[Occurrence]:
        # Entries whose own exam lies in [first_day, end_day), once per
        # (name, date), unless an entry of that (name, date) matches a
        # CourseExam of the term.
        candidates = [entry for entry in entries
                      if entry.exam_date is not None
                      and first_day <= entry.exam_date < end_day]
        if not candidates:
            return []
        index = ExamIndex.for_term(term)
        scheduled = {(entry.name, entry.exam_date) for entry in candidates
                     if index.match_entry(entry)}
        emitted: set[tuple[str, date]] = set()
        result: list[Occurrence] = []
        for entry in candidates:
            key = (entry.name, entry.exam_date)
            if key in scheduled or key in emitted:
                continue
            emitted.add(key)
            result.append(self._own_occurrence(entry, term))
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

    @staticmethod
    def _own_occurrence(entry: TimetableEntry, term) -> Occurrence:
        on = entry.exam_date
        start, end = entry_exam_window(entry)
        return Occurrence(
            id=f'exam:entry{entry.pk}:{on.isoformat()}',
            source='exam',
            kind='exam',
            title=f'{entry.name} 考试',
            subtitle=ENTRY_EXAM_NOTE,
            location=entry.exam_room,
            start=start,
            end=end,
            date=on,
            week=term.week_of(on),
            weekday=on.isoweekday(),
            start_section=None,
            end_section=None,
            color_key=entry.name,
            status='',
            ref={'entry_id': entry.pk},
            role='',
        )
