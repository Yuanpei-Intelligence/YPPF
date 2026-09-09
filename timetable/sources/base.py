"""
Event sources of the week view, the agenda and the ICS feed: the
``Occurrence`` value object, the ``EventSource`` protocol, the ``DateSpan``
of a date-based query and the config-driven registry ``load_sources``.
Contract: ``timetable/README.md`` §4.3 and §6.5.

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
from timetable.models import AcademicTerm

__all__ = [
    'DATETIME_FORMAT',
    'Occurrence',
    'EventSource',
    'DateSpan',
    'load_sources',
    'reset_sources_cache',
    'week_span',
    'occurrences_between',
    'term_occurrences_between',
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


class DateSpan:
    """
    An inclusive date range together with the active terms, resolving each
    date to the term it belongs to the way the agenda does (``README`` §6.5):
    the active term whose teaching span covers the date, the latest-starting
    one when several overlap, ``None`` outside every term. Built with one
    query by ``load``; ``week_of`` also numbers dates outside every term
    (relative to the latest term that has started, else the next one) so a
    live event on such a date still gets an integer ``Occurrence.week``.
    """

    def __init__(self, start: date, end: date,
                 terms: Iterable[AcademicTerm] = ()):
        self.start = start
        self.end = end
        self.terms: list[AcademicTerm] = sorted(
            terms, key=lambda term: (term.week1_monday, term.pk or 0), reverse=True)
        self._term_by_date: dict[date, AcademicTerm | None] = {}

    @classmethod
    def load(cls, start: date, end: date) -> 'DateSpan':
        """A span over ``start..end`` with every active term (one query)."""
        return cls(start, end, AcademicTerm.objects.filter(is_active=True))

    def __repr__(self) -> str:
        return (f'DateSpan({self.start.isoformat()}..{self.end.isoformat()}, '
                f'{len(self.terms)} term(s))')

    def dates(self) -> list[date]:
        """The dates of the span in order; empty when ``end < start``."""
        count = (self.end - self.start).days + 1
        return [self.start + timedelta(days=offset) for offset in range(max(count, 0))]

    def bounds(self) -> tuple[datetime, datetime]:
        """``[start, end)`` datetimes of the span (00:00 of the day after ``end``)."""
        return (datetime.combine(self.start, time.min),
                datetime.combine(self.end + timedelta(days=1), time.min))

    def term_of(self, on: date) -> AcademicTerm | None:
        """The term ``on`` belongs to (teaching span, latest-starting wins)."""
        try:
            return self._term_by_date[on]
        except KeyError:
            pass
        term = next((term for term in self.terms if term.covers(on)), None)
        self._term_by_date[on] = term
        return term

    def week_of(self, on: date) -> int:
        """
        Teaching week of ``on`` in its term; outside every term the week
        relative to the latest term that has started (or, before the first
        one, the next term — 0 or negative); 0 when there is no term at all.
        """
        term = self.term_of(on)
        if term is None:
            term = next((term for term in self.terms if term.week1_monday <= on), None)
        if term is None and self.terms:
            term = self.terms[-1]
        return term.week_of(on) if term is not None else 0


class EventSource(Protocol):
    """
    A pluggable provider of occurrences for the week view, the agenda and
    the ICS feed. ``occurrences`` (per term and teaching weeks) is required;
    ``occurrences_between`` (per dates, whatever the term) is optional —
    date-based sources such as activities implement it, term-based ones fall
    back to ``term_occurrences_between``. Callers ask for a date span through
    the module function ``occurrences_between``, which dispatches.
    """

    key: str
    label: str

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        """Occurrences of ``person`` in teaching weeks ``week_from..week_to``."""
        ...

    def occurrences_between(self, person, span: DateSpan,
                            settings) -> list[Occurrence]:
        """Occurrences of ``person`` on the dates of ``span`` (optional)."""
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


def occurrences_between(source: EventSource, person, span: DateSpan,
                        settings) -> list[Occurrence]:
    """
    Occurrences of ``source`` for ``person`` on the dates of ``span``,
    sorted. A source implementing ``occurrences_between`` is asked directly;
    any other one gets ``term_occurrences_between``. Empty for an empty span.
    """
    if span.end < span.start:
        return []
    method = getattr(source, 'occurrences_between', None)
    if callable(method):
        result = list(method(person, span, settings))
    else:
        result = term_occurrences_between(source, person, span, settings)
    result.sort(key=occurrence_sort_key)
    return result


def term_occurrences_between(source: EventSource, person, span: DateSpan,
                             settings) -> list[Occurrence]:
    """
    Default ``occurrences_between`` of a term-based source: ``occurrences``
    is called once per term that dates of ``span`` belong to, over the
    teaching weeks those dates cover, and the result is narrowed to exactly
    those dates. Dates outside every term yield nothing.
    """
    dates_by_term: dict[int, list[date]] = {}
    terms: dict[int, AcademicTerm] = {}
    for on in span.dates():
        term = span.term_of(on)
        if term is not None:
            terms[term.pk] = term
            dates_by_term.setdefault(term.pk, []).append(on)
    result: list[Occurrence] = []
    for pk, dates in dates_by_term.items():
        term = terms[pk]
        wanted = set(dates)
        week_from, week_to = term.week_of(dates[0]), term.week_of(dates[-1])
        result.extend(
            item for item in source.occurrences(person, term, week_from, week_to, settings)
            if item.date in wanted)
    result.sort(key=occurrence_sort_key)
    return result


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
