"""
Resolution of ``TimetableEntryOverride`` rows for one teaching week
(``timetable/README.md`` §8.2).

For a week *w* the applicable overrides (``week_start ≤ w ≤ week_end``,
``None`` bounds following the entry's own span) are applied in order of
descending range width, then ascending id, so a narrower or newer override
wins for every key — ``canceled`` included, which takes the last applied
override's value, and ``ignore_calendar`` (「照常上课」, §11), which
resolves into ``ResolvedWeek.ignore_calendar`` instead of a value. The
functions here are pure: they read model instances but never query, so
``expand_entries`` can resolve every week of a term from one prefetched
list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any, Iterable

from timetable.models import (
    OVERRIDE_FIELD_KEYS,
    AcademicTerm,
    TimetableEntry,
    TimetableEntryOverride,
)

__all__ = [
    'ResolvedWeek',
    'applicable_overrides',
    'resolve_week',
    'overrides_by_entry',
    'format_time',
]

_SECTION_KEYS = ('start_section', 'end_section')
_TIME_KEYS = ('start_time', 'end_time')


@dataclass
class ResolvedWeek:
    """
    The effective values of an entry in one week after its overrides;
    ``ignore_calendar`` is the resolved 「照常上课」 flag (README §11).
    """

    values: dict[str, Any]
    canceled: bool = False
    applied: list[TimetableEntryOverride] = field(default_factory=list)
    ignore_calendar: bool = False

    @property
    def modified(self) -> bool:
        """Whether at least one override applied to this week."""
        return bool(self.applied)


def format_time(value: time | str | None) -> str:
    """``'HH:MM'`` of a time (strings are returned trimmed)."""
    if isinstance(value, time):
        return value.strftime('%H:%M')
    return str(value or '').strip()


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    parts = str(value or '').strip().split(':')
    if len(parts) not in (2, 3):
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return time(hour, minute, second)
    except ValueError:
        return None


def _as_int(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def applicable_overrides(entry: TimetableEntry,
                         overrides: Iterable[TimetableEntryOverride],
                         week: int) -> list[TimetableEntryOverride]:
    """
    The overrides of ``entry`` covering ``week`` in application order:
    widest range first, equal widths by ascending id.
    """
    covering = [item for item in overrides if item.applies_to(week, entry)]

    def order(item: TimetableEntryOverride) -> tuple[int, int]:
        first, last = item.bounds(entry)
        return (-(last - first), item.pk or 0)

    covering.sort(key=order)
    return covering


def resolve_week(entry: TimetableEntry, overrides: Iterable[TimetableEntryOverride],
                 week: int, term: AcademicTerm | None = None) -> ResolvedWeek:
    """
    The effective field values of ``entry`` in ``week``: the entry's own
    values with every applicable override applied in order. Sections and
    times are coerced (a malformed value is ignored); when an override
    changes the sections without giving times, the times come from
    ``term.section_times`` (the entry's term when ``term`` is omitted).
    ``ignore_calendar`` takes the last applied boolean (a non-bool value is
    ignored) and is not part of ``values``.
    """
    values: dict[str, Any] = {
        'name': entry.name,
        'teacher': entry.teacher,
        'room': entry.room,
        'weekday': int(entry.weekday),
        'start_section': int(entry.start_section),
        'end_section': int(entry.end_section),
        'start_time': entry.start_time,
        'end_time': entry.end_time,
        'note': entry.note,
        'tag': entry.tag,
        'color': entry.color,
    }
    applied = applicable_overrides(entry, overrides, week)
    canceled = False
    ignore_calendar = False
    sections_changed = False
    times_changed = False
    for override in applied:
        canceled = bool(override.canceled)
        fields = override.fields if isinstance(override.fields, dict) else {}
        for key in OVERRIDE_FIELD_KEYS:
            if key not in fields:
                continue
            raw = fields[key]
            if key == 'ignore_calendar':
                if isinstance(raw, bool):
                    ignore_calendar = raw
            elif key == 'weekday':
                weekday = _as_int(raw, 1, 7)
                if weekday is not None:
                    values[key] = weekday
            elif key in _SECTION_KEYS:
                section = _as_int(raw, 0, 99)
                if section is not None:
                    values[key] = section
                    sections_changed = True
            elif key in _TIME_KEYS:
                parsed = _parse_time(raw)
                if parsed is not None:
                    values[key] = parsed
                    times_changed = True
            else:
                values[key] = '' if raw is None else str(raw)
    if sections_changed and not times_changed:
        if term is None:
            term = entry.term
        start = end = None
        if values['start_section'] and values['end_section']:
            start = term.section_time(values['start_section'])
            end = term.section_time(values['end_section'])
        if start is not None and end is not None:
            values['start_time'], values['end_time'] = start[0], end[1]
    if values['end_time'] <= values['start_time']:
        # An inconsistent pair (e.g. only one time overridden) falls back to
        # the entry's own times rather than producing a negative lesson.
        values['start_time'], values['end_time'] = entry.start_time, entry.end_time
    return ResolvedWeek(values, canceled, applied, ignore_calendar)


def overrides_by_entry(
    entries: Iterable[TimetableEntry],
) -> dict[int, list[TimetableEntryOverride]]:
    """
    ``{entry id: overrides}`` for ``entries`` — from a prefetch when present,
    otherwise one query for all of them.
    """
    entries = list(entries)
    result: dict[int, list[TimetableEntryOverride]] = {}
    missing: list[int] = []
    for entry in entries:
        cache = getattr(entry, '_prefetched_objects_cache', None)
        if cache is not None and 'overrides' in cache:
            result[entry.pk] = list(cache['overrides'])
        elif entry.pk is not None:
            missing.append(entry.pk)
    if missing:
        for override in (TimetableEntryOverride.objects
                         .filter(entry_id__in=missing).order_by('id')):
            result.setdefault(override.entry_id, []).append(override)
        for pk in missing:
            result.setdefault(pk, [])
    return result
