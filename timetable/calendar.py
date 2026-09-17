"""
Academic calendar (校历) adapter of the timetable (``timetable/README.md``
§6.4).

The calendar itself lives in the base app ``semester``
(``semester.models.CalendarEvent`` rows edited in admin, read through
``semester.calendar``); this module maps it onto terms — the calendar
spanning a term's teaching weeks, the ``CalendarEvent`` / ``WeekDay``
payload shapes of the API — and holds the JSON transcription format behind
the ``import_academic_calendar`` command. Calendars are always built fresh
(one query), so admin edits show on the next request.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

from django.db import transaction

from semester.calendar import AcademicCalendar, calendar_between, events_between
from semester.models import CalendarEvent
from timetable.models import AcademicTerm

__all__ = [
    'MAX_TOTAL_WEEKS',
    'term_span',
    'calendar_for',
    'calendars_for',
    'event_payload',
    'calendar_payload',
    'day_info',
    'week_days',
    'CalendarSpecError',
    'CalendarEventSpec',
    'CalendarSpec',
    'CalendarImportResult',
    'parse_calendar_spec',
    'replacement_window',
    'apply_calendar_spec',
]

MAX_TOTAL_WEEKS = 30
_TERM_CODE_RE = re.compile(r'^(\d{2}|\d{4})-(\d{2}|\d{4})-\d$')
_SPEC_KEYS = frozenset({'term', 'name', 'week1_monday', 'total_weeks',
                        'exam_week_start', 'events'})
_SPEC_REQUIRED = frozenset({'term', 'name', 'week1_monday', 'total_weeks', 'events'})
_EVENT_KEYS = frozenset({'kind', 'start', 'end', 'name', 'follows_weekday', 'note'})
_EVENT_REQUIRED = ('kind', 'start', 'end', 'name')
# Events must lie in this window around week 1 — it catches a wrong year.
_BEFORE_WEEK1 = timedelta(days=42)
_AFTER_WEEK1 = timedelta(days=364)


# --- calendars of terms ------------------------------------------------------

def term_span(term: AcademicTerm) -> tuple[date, date]:
    """``(week1_monday, Sunday of the last teaching week)`` of ``term``."""
    return term.week1_monday, term.end_date()


def calendar_for(term: AcademicTerm) -> AcademicCalendar:
    """A fresh calendar spanning the teaching weeks of ``term`` (one query)."""
    return calendar_between(*term_span(term))


def calendars_for(terms: Iterable[AcademicTerm]) -> dict[str, AcademicCalendar]:
    """Calendars of several terms keyed by term code, from one query."""
    spans = {term.code: term_span(term) for term in terms}
    if not spans:
        return {}
    events = events_between(min(start for start, _ in spans.values()),
                            max(end for _, end in spans.values()))
    return {code: AcademicCalendar(start, end, events)
            for code, (start, end) in spans.items()}


def event_payload(event: CalendarEvent) -> dict[str, Any]:
    """JSON shape of ``CalendarEvent`` in ``timetable/README.md`` §6.4."""
    return {
        'kind': str(event.kind),
        'start': event.start_date.isoformat(),
        'end': event.end_date.isoformat(),
        'name': event.name,
        'follows_weekday': (int(event.follows_weekday)
                            if event.follows_weekday is not None else None),
    }


def calendar_payload(calendar: AcademicCalendar) -> list[dict[str, Any]]:
    """``Term.calendar``: the events overlapping the calendar's range, ordered."""
    return [event_payload(event) for event in calendar.events]


def day_info(on: date, calendar: AcademicCalendar | None = None) -> dict[str, Any]:
    """
    JSON shape of ``WeekDay`` (§6.4) for one date: the deciding event's kind
    and name and, on a swap date, the weekday it follows. Pass a
    ``calendar`` covering ``on`` to avoid a query.
    """
    if calendar is None or not calendar.covers(on):
        calendar = calendar_between(on, on)
    event = calendar.event_of(on)
    follows = None
    if (event is not None and event.kind == CalendarEvent.Kind.SWAP
            and event.follows_weekday):
        follows = int(event.follows_weekday)
    return {
        'date': on.isoformat(),
        'weekday': on.isoweekday(),
        'kind': str(event.kind) if event is not None else None,
        'label': event.name if event is not None else None,
        'follows_weekday': follows,
    }


def week_days(term: AcademicTerm, week: int,
              calendar: AcademicCalendar | None = None) -> list[dict[str, Any]]:
    """``WeekView.days``: one ``WeekDay`` per date (Mon..Sun) of ``week``."""
    dates = term.week_dates(week)
    if calendar is None or not calendar.covers(dates[0], dates[-1]):
        calendar = calendar_between(dates[0], dates[-1])
    return [day_info(on, calendar) for on in dates]


# --- JSON transcription of one term (import_academic_calendar) --------------

class CalendarSpecError(ValueError):
    """A calendar JSON that cannot be imported; ``problems`` lists every issue."""

    def __init__(self, problems: Iterable[str]):
        self.problems = list(problems)
        super().__init__('; '.join(self.problems))


@dataclass
class CalendarEventSpec:
    """One validated event of the JSON file."""

    kind: str
    start: date
    end: date
    name: str
    follows_weekday: int | None = None
    note: str = ''

    def to_model(self) -> CalendarEvent:
        return CalendarEvent(
            kind=self.kind, start_date=self.start, end_date=self.end,
            name=self.name, follows_weekday=self.follows_weekday, note=self.note)


@dataclass
class CalendarSpec:
    """A validated calendar JSON file: the term and its events."""

    code: str
    name: str
    week1_monday: date
    total_weeks: int
    events: list[CalendarEventSpec] = field(default_factory=list)
    exam_week_start: int | None = None      # weeks from here are 考试周 (§8.4)

    @property
    def end_date(self) -> date:
        """Sunday of the last teaching week."""
        return self.week1_monday + timedelta(days=7 * self.total_weeks - 1)

    def week_of(self, on: date) -> int:
        """1-based teaching week of a date (may be < 1 or > ``total_weeks``)."""
        return (on - self.week1_monday).days // 7 + 1


@dataclass
class CalendarImportResult:
    """What ``apply_calendar_spec`` did (or, on a dry run, would do)."""

    spec: CalendarSpec
    term: AcademicTerm | None            # None on a dry run that would create it
    term_created: bool
    term_changes: dict[str, tuple[Any, Any]]
    window: tuple[date, date]
    removed: int
    written: int
    dry_run: bool


def parse_calendar_spec(data: Any) -> CalendarSpec:
    """
    Validate the JSON document of ``timetable/README.md`` §6.4 and return a
    ``CalendarSpec``. Every problem found is reported at once through
    ``CalendarSpecError``: unknown/missing keys, malformed dates, a
    ``week1_monday`` that is not a Monday, an event whose ``end`` precedes
    ``start``, a swap without ``follows_weekday`` (or any other kind with
    one), duplicate events and events outside the term's year.
    """
    if not isinstance(data, dict):
        raise CalendarSpecError(['the document must be a JSON object'])
    problems: list[str] = []
    _check_keys(data, _SPEC_KEYS, _SPEC_REQUIRED, 'document', problems)
    code = _text(data.get('term'), 'term', 16, problems)
    if code and not _TERM_CODE_RE.match(code):
        problems.append(f'term: {code!r} is not a term code like 26-27-1')
    name = _text(data.get('name'), 'name', 32, problems)
    week1_monday = _date(data.get('week1_monday'), 'week1_monday', problems)
    if week1_monday is not None and week1_monday.isoweekday() != 1:
        problems.append(f'week1_monday: {week1_monday} is not a Monday')
    total_weeks = data.get('total_weeks')
    if not _is_int(total_weeks) or not 1 <= total_weeks <= MAX_TOTAL_WEEKS:
        problems.append(f'total_weeks: must be an integer between 1 and {MAX_TOTAL_WEEKS}')
        total_weeks = None
    exam_week_start = data.get('exam_week_start')
    if exam_week_start is not None:
        upper = total_weeks if total_weeks is not None else MAX_TOTAL_WEEKS
        if not _is_int(exam_week_start) or not 1 <= exam_week_start <= upper:
            problems.append(f'exam_week_start: must be an integer between 1 and '
                            f'total_weeks ({upper}), or absent')
            exam_week_start = None
    events: list[CalendarEventSpec] = []
    raw_events = data.get('events')
    if not isinstance(raw_events, list):
        problems.append('events: must be a list')
    else:
        seen: set[tuple] = set()
        for index, raw in enumerate(raw_events, start=1):
            event = _parse_event(raw, f'events[{index}]', problems)
            if event is None:
                continue
            key = (event.kind, event.start, event.end, event.name)
            if key in seen:
                problems.append(f'events[{index}]: duplicate of an earlier event')
                continue
            seen.add(key)
            events.append(event)
    if week1_monday is not None:
        low, high = week1_monday - _BEFORE_WEEK1, week1_monday + _AFTER_WEEK1
        for event in events:
            if event.start < low or event.end > high:
                problems.append(
                    f'events: {event.name} ({event.start}..{event.end}) lies '
                    f'outside the term year {low}..{high} — wrong year?')
    if problems:
        raise CalendarSpecError(problems)
    return CalendarSpec(code, name, week1_monday, total_weeks, events,
                        exam_week_start=exam_week_start)


def _parse_event(raw: Any, where: str, problems: list[str]) -> CalendarEventSpec | None:
    if not isinstance(raw, dict):
        problems.append(f'{where}: must be an object')
        return None
    before = len(problems)
    _check_keys(raw, _EVENT_KEYS, _EVENT_REQUIRED, where, problems)
    kind = raw.get('kind')
    if kind not in CalendarEvent.Kind.values:
        problems.append(f'{where}.kind: {kind!r} is not one of '
                        f'{", ".join(CalendarEvent.Kind.values)}')
    start = _date(raw.get('start'), f'{where}.start', problems)
    end = _date(raw.get('end'), f'{where}.end', problems)
    if start is not None and end is not None and end < start:
        problems.append(f'{where}: end {end} is before start {start}')
    name = _text(raw.get('name'), f'{where}.name', 64, problems)
    follows_weekday = raw.get('follows_weekday')
    if kind == CalendarEvent.Kind.SWAP:
        if not _is_int(follows_weekday) or not 1 <= follows_weekday <= 7:
            problems.append(f'{where}.follows_weekday: a swap needs the weekday '
                            f'it follows, 1 (Monday) .. 7 (Sunday)')
    elif follows_weekday is not None:
        problems.append(f'{where}.follows_weekday: only allowed for kind "swap"')
    note = raw.get('note') or ''
    if not isinstance(note, str) or len(note) > 200:
        problems.append(f'{where}.note: must be a string of at most 200 characters')
    if len(problems) > before:
        return None
    return CalendarEventSpec(str(kind), start, end, name,
                             follows_weekday if kind == CalendarEvent.Kind.SWAP else None,
                             note.strip())


def _check_keys(data: dict, allowed: Iterable[str], required: Iterable[str],
                where: str, problems: list[str]) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        problems.append(f'{where}: unknown key(s) {", ".join(unknown)}')
    missing = sorted(set(required) - set(data))
    if missing:
        problems.append(f'{where}: missing key(s) {", ".join(missing)}')


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value: Any, where: str, max_length: int, problems: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        problems.append(f'{where}: must be a non-empty string')
        return ''
    value = value.strip()
    if len(value) > max_length:
        problems.append(f'{where}: longer than {max_length} characters')
    return value


def _date(value: Any, where: str, problems: list[str]) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    problems.append(f'{where}: {value!r} is not an ISO date (YYYY-MM-DD)')
    return None


def replacement_window(spec: CalendarSpec) -> tuple[date, date]:
    """
    The inclusive date range whose ``CalendarEvent`` rows the file owns:
    from week 1 (or the file's earliest event, if earlier) to the Sunday of
    the last teaching week (or the file's latest event, if later — the exam
    period and the vacation after a term belong to that term's file).
    """
    start, end = spec.week1_monday, spec.end_date
    for event in spec.events:
        start = min(start, event.start)
        end = max(end, event.end)
    return start, end


def apply_calendar_spec(spec: CalendarSpec, *, dry_run: bool = False) -> CalendarImportResult:
    """
    Upsert the ``AcademicTerm`` of ``spec`` (``name``, ``week1_monday``,
    ``total_weeks``, ``exam_week_start``; ``section_times``/``is_active`` of
    an existing term are kept) and replace the ``CalendarEvent`` rows
    overlapping ``replacement_window(spec)`` with the file's events, in one
    transaction. Idempotent: a second run removes exactly the rows the
    first one wrote. With ``dry_run`` nothing is written and the result
    describes what would happen.
    """
    window = replacement_window(spec)
    fields = {'name': spec.name, 'week1_monday': spec.week1_monday,
              'total_weeks': spec.total_weeks,
              'exam_week_start': spec.exam_week_start}
    with transaction.atomic():
        terms = AcademicTerm.objects.filter(code=spec.code)
        if not dry_run:
            terms = terms.select_for_update()
        term = terms.first()
        created = term is None
        changes: dict[str, tuple[Any, Any]] = {}
        if term is not None:
            changes = {name: (getattr(term, name), value)
                       for name, value in fields.items()
                       if getattr(term, name) != value}
        stale = CalendarEvent.objects.filter(
            start_date__lte=window[1], end_date__gte=window[0])
        if dry_run:
            return CalendarImportResult(spec, term, created, changes, window,
                                        stale.count(), len(spec.events), True)
        if created:
            term = AcademicTerm.objects.create(code=spec.code, **fields)
        elif changes:
            for name, (_, value) in changes.items():
                setattr(term, name, value)
            term.save(update_fields=list(changes))
        removed, _ = stale.delete()
        CalendarEvent.objects.bulk_create([event.to_model() for event in spec.events])
    return CalendarImportResult(spec, term, created, changes, window,
                                removed, len(spec.events), False)
