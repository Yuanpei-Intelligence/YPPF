"""
Source that expands stored ``TimetableEntry`` rows (portal/paste imports and
manual entries) into occurrences, following the university calendar.
Contract: ``timetable/README.md`` §4.3 and §6.4.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from semester.calendar import AcademicCalendar, calendar_between
from timetable.models import TimetableEntry
from timetable.sources.base import Occurrence, occurrence_sort_key

__all__ = ['expand_entries', 'StoredEntriesSource']


def expand_entries(entries: Iterable[TimetableEntry], term,
                   week_from: int, week_to: int,
                   calendar: AcademicCalendar | None = None) -> list[Occurrence]:
    """
    Expand entries into one occurrence per lesson in teaching weeks
    ``week_from..week_to`` of ``term``, honouring week range, parity and
    the university calendar: holiday and exam dates produce nothing and a
    调休 swap date carries the lessons of the weekday it follows (week range
    and parity judged by the swap date's own week) instead of its own. An
    occurrence's ``date``/``weekday``/``week`` are always the real ones, so
    a swap day's lessons sit in that day's column, and ``id`` stays
    ``'{source}:{entry_id}:{date}'``.

    ``calendar`` (a ``semester.calendar.AcademicCalendar``) must cover the
    expanded dates; when missing or too narrow one is built (one query).
    Hidden entries are expanded too, flagged ``hidden=True``; callers filter.
    """
    occurrences: list[Occurrence] = []
    if week_from > week_to:
        return occurrences
    entries = list(entries)
    if not entries:
        return occurrences
    first_day = term.date_of(week_from, 1)
    last_day = term.date_of(week_to, 7)
    if calendar is None or not calendar.covers(first_day, last_day):
        calendar = calendar_between(first_day, last_day)
    for week in range(week_from, week_to + 1):
        slots = _class_slots(calendar, term, week)
        if not slots:
            continue
        for entry in entries:
            if not entry.occurs_in_week(week):
                continue
            for on in slots.get(entry.weekday, ()):
                occurrences.append(_occurrence(entry, on, week))
    occurrences.sort(key=occurrence_sort_key)
    return occurrences


def _class_slots(calendar: AcademicCalendar, term, week: int) -> dict[int, list[date]]:
    # {weekday whose timetable applies: dates of ``week`` with classes}
    slots: dict[int, list[date]] = {}
    for weekday in range(1, 8):
        on = term.date_of(week, weekday)
        if not calendar.is_class_day(on):
            continue
        slots.setdefault(calendar.effective_weekday(on), []).append(on)
    return slots


def _occurrence(entry: TimetableEntry, on: date, week: int) -> Occurrence:
    return Occurrence(
        id=f'{entry.source}:{entry.pk}:{on.isoformat()}',
        source=entry.source,
        kind=entry.kind,
        title=entry.name,
        subtitle=entry.teacher,
        location=entry.room,
        start=entry.start_at(on),
        end=entry.end_at(on),
        date=on,
        week=week,
        weekday=on.isoweekday(),
        start_section=entry.start_section or None,
        end_section=entry.end_section or None,
        color_key=entry.name,
        status='',
        ref={'entry_id': entry.pk},
        hidden=entry.hidden,
    )


class StoredEntriesSource:
    """School courses (portal/paste) and manual entries stored in YPPF."""

    key = 'stored'
    label = '课程'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        entries = TimetableEntry.objects.filter(
            person=person, term=term, hidden=False).order_by('id')
        return expand_entries(entries, term, week_from, week_to)
