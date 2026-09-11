"""
Read API of the university calendar (校历).

``semester.models.CalendarEvent`` rows are global and keyed by date: they
are imported from the published 校历 (``timetable`` command
``import_academic_calendar``) and edited in Django admin. Every consumer —
the timetable, activities, anything that must know whether a date has
classes — builds an ``AcademicCalendar`` for the dates it cares about and
asks it. Nothing here is cached: a calendar is one query when built and the
next build reflects admin edits, so callers must not keep calendars across
requests.

Semantics (``timetable/README.md`` §6.4): ``holiday`` and ``exam`` dates
have no classes; a ``swap`` date follows the timetable of weekday
``follows_weekday``; ``info`` is a label only. A date covered by several
events takes the highest-precedence one — holiday, then exam, then swap,
then info; among equal kinds the earliest-starting (then first stored)
event wins.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from semester.models import CalendarEvent

__all__ = [
    'KIND_PRIORITY',
    'NO_CLASS_KINDS',
    'AcademicCalendar',
    'events_between',
    'calendar_between',
    'is_class_day',
    'effective_weekday',
]

KIND_PRIORITY: dict[str, int] = {
    CalendarEvent.Kind.HOLIDAY: 0,
    CalendarEvent.Kind.EXAM: 1,
    CalendarEvent.Kind.SWAP: 2,
    CalendarEvent.Kind.INFO: 3,
}
NO_CLASS_KINDS = frozenset({CalendarEvent.Kind.HOLIDAY, CalendarEvent.Kind.EXAM})


def events_between(start: date, end: date) -> list[CalendarEvent]:
    """
    Events overlapping the inclusive range ``start..end``, ordered by
    ``(start_date, id)``. One query; an empty list when ``end < start``.
    """
    if end < start:
        return []
    return list(CalendarEvent.objects
                .filter(start_date__lte=end, end_date__gte=start)
                .order_by('start_date', 'id'))


class AcademicCalendar:
    """
    The calendar of one inclusive date range, answering per-date questions
    from the events loaded at construction. Dates outside the range raise
    ``ValueError`` (the answer would silently be "a normal day").
    """

    def __init__(self, start: date, end: date, events: Iterable[CalendarEvent]):
        self.start = start
        self.end = end
        ordered = sorted(enumerate(events),
                         key=lambda item: (item[1].start_date, item[0]))
        self.events: list[CalendarEvent] = [
            event for _, event in ordered
            if event.start_date <= end and event.end_date >= start
        ]
        self._by_date: dict[date, CalendarEvent | None] = {}

    def __repr__(self) -> str:
        return (f'AcademicCalendar({self.start.isoformat()}..{self.end.isoformat()}, '
                f'{len(self.events)} event(s))')

    def covers(self, start: date, end: date | None = None) -> bool:
        """Whether the range ``start..end`` (or the single date) lies inside."""
        if end is None:
            end = start
        return self.start <= start and end <= self.end

    def event_of(self, on: date) -> CalendarEvent | None:
        """The event deciding ``on`` (see the module precedence), or ``None``."""
        if not self.covers(on):
            raise ValueError(
                f'{on.isoformat()} is outside the calendar range '
                f'{self.start.isoformat()}..{self.end.isoformat()}')
        try:
            return self._by_date[on]
        except KeyError:
            pass
        best: CalendarEvent | None = None
        for event in self.events:
            if not event.start_date <= on <= event.end_date:
                continue
            if best is None or _priority(event) < _priority(best):
                best = event
        self._by_date[on] = best
        return best

    def kind_of(self, on: date) -> tuple[str, CalendarEvent] | None:
        """``(kind, event)`` of the deciding event of ``on``, or ``None``."""
        event = self.event_of(on)
        if event is None:
            return None
        return str(event.kind), event

    def is_class_day(self, on: date) -> bool:
        """Whether classes take place on ``on`` (not a holiday/exam date)."""
        event = self.event_of(on)
        return event is None or event.kind not in NO_CLASS_KINDS

    def effective_weekday(self, on: date) -> int:
        """
        The weekday (1=Mon..7=Sun) whose timetable applies on ``on``:
        ``follows_weekday`` on a swap date, otherwise the real weekday.
        A swap inside a holiday/exam period is overridden by those.
        """
        event = self.event_of(on)
        if (event is not None and event.kind == CalendarEvent.Kind.SWAP
                and event.follows_weekday):
            return int(event.follows_weekday)
        return on.isoweekday()

    def label(self, on: date) -> str | None:
        """The name of the deciding event of ``on``, or ``None``."""
        event = self.event_of(on)
        return event.name if event is not None else None


def _priority(event: CalendarEvent) -> int:
    return KIND_PRIORITY.get(str(event.kind), len(KIND_PRIORITY))


def calendar_between(start: date, end: date) -> AcademicCalendar:
    """A fresh ``AcademicCalendar`` of ``start..end`` (one query)."""
    return AcademicCalendar(start, end, events_between(start, end))


def is_class_day(on: date) -> bool:
    """Whether ``on`` has classes according to the calendar (one query)."""
    return calendar_between(on, on).is_class_day(on)


def effective_weekday(on: date) -> int:
    """The weekday whose timetable applies on ``on`` (one query)."""
    return calendar_between(on, on).effective_weekday(on)
