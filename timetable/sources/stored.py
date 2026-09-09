"""
Source that expands stored ``TimetableEntry`` rows (portal/paste imports and
manual entries) into occurrences. Contract: ``timetable/README.md`` §4.3.
"""
from __future__ import annotations

from typing import Iterable

from timetable.models import TimetableEntry
from timetable.sources.base import Occurrence, occurrence_sort_key

__all__ = ['expand_entries', 'StoredEntriesSource']


def expand_entries(entries: Iterable[TimetableEntry], term,
                   week_from: int, week_to: int) -> list[Occurrence]:
    """
    Expand entries into one occurrence per lesson in teaching weeks
    ``week_from..week_to`` of ``term``, honouring week range and parity.
    Hidden entries are expanded too, flagged ``hidden=True``; callers filter.
    """
    occurrences: list[Occurrence] = []
    if week_from > week_to:
        return occurrences
    for entry in entries:
        first = max(week_from, entry.week_start)
        last = min(week_to, entry.week_end)
        for week in range(first, last + 1):
            if not entry.occurs_in_week(week):
                continue
            on = term.date_of(week, entry.weekday)
            occurrences.append(Occurrence(
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
                weekday=entry.weekday,
                start_section=entry.start_section or None,
                end_section=entry.end_section or None,
                color_key=entry.name,
                status='',
                ref={'entry_id': entry.pk},
                hidden=entry.hidden,
            ))
    occurrences.sort(key=occurrence_sort_key)
    return occurrences


class StoredEntriesSource:
    """School courses (portal/paste) and manual entries stored in YPPF."""

    key = 'stored'
    label = '课程'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        entries = TimetableEntry.objects.filter(
            person=person, term=term, hidden=False).order_by('id')
        return expand_entries(entries, term, week_from, week_to)
