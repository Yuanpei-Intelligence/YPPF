"""
Event sources of the week view: the ``Occurrence`` value object, the
``EventSource`` protocol and the config-driven registry ``load_sources``.
Contract: ``timetable/README.md`` §4.3.

Sources that read other apps (``college``, ``activity``, ``appoint``) import
those apps lazily inside ``occurrences`` and are only loaded when listed in
``config.json → timetable.sources``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from importlib import import_module
from typing import Any, Iterable, Protocol

from timetable.config import CONFIG

__all__ = [
    'DATETIME_FORMAT',
    'Occurrence',
    'EventSource',
    'load_sources',
    'reset_sources_cache',
    'week_span',
    'occurrence_sort_key',
]

logger = logging.getLogger(__name__)

DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


@dataclass(kw_only=True)
class Occurrence:
    """One event on one date of the timetable."""

    id: str                 # stable: f'{source}:{key}:{date}'
    source: str             # 'portal' | 'paste' | 'manual' | 'college' | 'activity' | 'appoint'
    kind: str               # 'course' | 'college' | 'activity' | 'appoint' | 'custom'
    title: str
    subtitle: str = ''
    location: str = ''
    start: datetime
    end: datetime
    date: date
    week: int
    weekday: int
    start_section: int | None = None
    end_section: int | None = None
    color_key: str = ''     # stable colouring key (course name or id)
    status: str = ''        # '' | 'canceled' | 'checked_in' | 'applied'
    ref: dict = field(default_factory=dict)
    hidden: bool = False

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of ``Occurrence`` in ``timetable/README.md`` §4.6."""
        return {
            'id': self.id,
            'source': self.source,
            'kind': self.kind,
            'title': self.title,
            'subtitle': self.subtitle,
            'location': self.location,
            'start': self.start.strftime(DATETIME_FORMAT),
            'end': self.end.strftime(DATETIME_FORMAT),
            'date': self.date.isoformat(),
            'week': self.week,
            'weekday': self.weekday,
            'start_section': self.start_section,
            'end_section': self.end_section,
            'color_key': self.color_key,
            'status': self.status,
            'ref': dict(self.ref),
            'hidden': self.hidden,
        }

    def overlaps(self, other: 'Occurrence') -> bool:
        """Whether two occurrences on the same date overlap in time."""
        return (self.date == other.date
                and self.start < other.end and other.start < self.end)


class EventSource(Protocol):
    """A pluggable provider of occurrences for the week view and the ICS feed."""

    key: str
    label: str

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        """Occurrences of ``person`` in teaching weeks ``week_from..week_to``."""
        ...


def occurrence_sort_key(occurrence: Occurrence) -> tuple:
    return (occurrence.date, occurrence.start, occurrence.end,
            occurrence.title, occurrence.id)


def week_span(term, week_from: int, week_to: int) -> tuple[datetime, datetime]:
    """
    ``[start, end)`` datetimes covering teaching weeks ``week_from..week_to``
    of ``term`` (Monday 00:00 of the first week to Monday 00:00 after the
    last week).
    """
    start = datetime.combine(term.date_of(week_from, 1), time.min)
    end = datetime.combine(term.date_of(week_to, 7) + timedelta(days=1), time.min)
    return start, end


_cache: list[EventSource] | None = None


def load_sources(paths: Iterable[str] | None = None) -> list[EventSource]:
    """
    Instantiate the event sources listed in ``CONFIG.sources`` (cached), or
    the given dotted paths (not cached). Entries that cannot be imported or
    instantiated are logged and skipped, never fatal.
    """
    global _cache
    if paths is not None:
        return _instantiate(paths)
    if _cache is None:
        _cache = _instantiate(CONFIG.sources)
    return list(_cache)


def reset_sources_cache() -> None:
    """Forget the cached source instances (tests and config reloads)."""
    global _cache
    _cache = None


def _instantiate(paths: Iterable[str]) -> list[EventSource]:
    sources: list[EventSource] = []
    seen: set[str] = set()
    for path in paths:
        source = _load_source(str(path))
        if source is None or source.key in seen:
            continue
        seen.add(source.key)
        sources.append(source)
    return sources


def _load_source(path: str) -> EventSource | None:
    module_name, _, class_name = path.strip().rpartition('.')
    if not module_name or not class_name:
        logger.warning('timetable source %r skipped: not a dotted path', path)
        return None
    try:
        module = import_module(module_name)
        source_class = getattr(module, class_name)
        source = source_class()
    except (ImportError, AttributeError, TypeError) as exc:
        logger.warning('timetable source %r skipped: %s', path, exc)
        return None
    if (not isinstance(getattr(source, 'key', None), str)
            or not callable(getattr(source, 'occurrences', None))):
        logger.warning('timetable source %r skipped: not an EventSource', path)
        return None
    if not isinstance(getattr(source, 'label', None), str):
        source.label = source.key
    return source
