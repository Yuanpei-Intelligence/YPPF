"""
Source that expands stored ``TimetableEntry`` rows (portal/paste imports and
manual entries) into occurrences, following the university calendar and
the entries' per-week overrides (or, for the term overview, only the
overrides).
Contract: ``timetable/README.md`` §4.3, §6.4, §8.2, §8.3, §10 and §11.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from semester.calendar import AcademicCalendar, calendar_between
from timetable.models import TimetableEntry, TimetableEntryOverride
from timetable.overrides import ResolvedWeek, overrides_by_entry, resolve_week
from timetable.sources.base import Occurrence, occurrence_sort_key

__all__ = ['expand_entries', 'StoredEntriesSource']


def expand_entries(entries: Iterable[TimetableEntry], term,
                   week_from: int, week_to: int,
                   calendar: AcademicCalendar | None = None, *,
                   overrides: dict[int, list[TimetableEntryOverride]] | None = None,
                   ) -> list[Occurrence]:
    """
    Expand entries into one occurrence per lesson in teaching weeks
    ``week_from..week_to`` of ``term``, honouring week range, parity, the
    entries' overrides (§8.2) and the university calendar (§11):

    - a lesson whose own date is a holiday or exam date, or a 调休 swap
      date that follows another weekday, is kept with ``status='suspended'``;
    - a swap date carries the lessons of the weekday it follows as normal
      occurrences with ``swap_from`` set to that weekday (week range and
      parity judged by the swap date's own week);
    - entries of category ``exam`` and weeks whose overrides resolve
      ``ignore_calendar`` (「照常上课」) keep their own date as a normal
      occurrence whatever the calendar says and get no swap copy.

    An occurrence's ``date``/``weekday``/``week`` are always the real ones,
    so a swap day's lessons sit in that day's column, and ``id`` stays
    ``'{source}:{entry_id}:{date}'`` — unique, because a lesson is
    suspended only on its own date and copied only to other dates.

    Overrides: a canceled week yields nothing; an overridden ``weekday``
    moves the lesson to that weekday of the same teaching week (the
    calendar rules of the target date apply); the other keys replace the
    entry's values and ``modified`` marks the occurrence. ``overrides`` maps
    entry ids to their override rows; when omitted they are read from the
    prefetch or with one query.

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
    if overrides is None:
        overrides = overrides_by_entry(entries)
    first_day = term.date_of(week_from, 1)
    last_day = term.date_of(week_to, 7)
    if calendar is None or not calendar.covers(first_day, last_day):
        calendar = calendar_between(first_day, last_day)
    for week in range(week_from, week_to + 1):
        class_days, swap_days = _week_calendar(calendar, term, week)
        for entry in entries:
            if not entry.occurs_in_week(week):
                continue
            resolved = resolve_week(entry, overrides.get(entry.pk, ()), week, term)
            if resolved.canceled:
                continue
            weekday = resolved.values['weekday']
            own_day = term.date_of(week, weekday)
            exempt = (entry.category == TimetableEntry.Category.EXAM
                      or resolved.ignore_calendar)
            status = '' if exempt or own_day in class_days else 'suspended'
            occurrences.append(
                _occurrence(entry, resolved, own_day, week, status=status))
            if exempt:
                continue
            for on in swap_days.get(weekday, ()):
                occurrences.append(
                    _occurrence(entry, resolved, on, week, swap_from=weekday))
    occurrences.sort(key=occurrence_sort_key)
    return occurrences


def _week_calendar(calendar: AcademicCalendar, term,
                   week: int) -> tuple[set[date], dict[int, list[date]]]:
    # ``(dates of week that hold their own weekday's lessons, {weekday: the
    # 调休 dates of week that follow it})``; holiday and exam dates are in
    # neither.
    class_days: set[date] = set()
    swap_days: dict[int, list[date]] = {}
    for weekday in range(1, 8):
        on = term.date_of(week, weekday)
        if not calendar.is_class_day(on):
            continue
        followed = calendar.effective_weekday(on)
        if followed == weekday:
            class_days.add(on)
        else:
            swap_days.setdefault(followed, []).append(on)
    return class_days, swap_days


def _occurrence(entry: TimetableEntry, resolved: ResolvedWeek, on: date,
                week: int, *, status: str = '',
                swap_from: int | None = None) -> Occurrence:
    values = resolved.values
    return Occurrence(
        id=f'{entry.source}:{entry.pk}:{on.isoformat()}',
        source=entry.source,
        kind=entry.kind,
        title=values['name'],
        subtitle=values['teacher'],
        location=values['room'],
        start=datetime.combine(on, values['start_time']),
        end=datetime.combine(on, values['end_time']),
        date=on,
        week=week,
        weekday=on.isoweekday(),
        start_section=values['start_section'] or None,
        end_section=values['end_section'] or None,
        color_key=values['name'],
        status=status,
        ref={'entry_id': entry.pk},
        hidden=entry.hidden,
        role=str(entry.role),
        tag=values['tag'],
        modified=resolved.modified,
        swap_from=swap_from,
    )


class StoredEntriesSource:
    """
    School courses (portal/paste) and manual entries stored in YPPF. Honours
    ``settings.show_courses`` and skips entries whose effective tag is in
    ``settings.hidden_tags`` (§8.3). Term-based: date-span queries go
    through the default ``timetable.sources.base.term_occurrences_between``.
    ``rule_occurrences`` (the term overview, §10) expands the same entries
    without the university calendar.
    """

    key = 'stored'
    label = '课程'
    setting = 'show_courses'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        return self._expand(person, term, week_from, week_to, settings, None)

    def rule_occurrences(self, person, term, week_from: int, week_to: int,
                         settings) -> list[Occurrence]:
        """
        The weekly rule of the entries in weeks ``week_from..week_to``: like
        ``occurrences`` (toggle, hidden entries, hidden tags, overrides) but
        expanded against an empty calendar, so holiday and exam dates keep
        their lessons as normal occurrences (never ``'suspended'``) and a
        调休 swap date adds none (README §10, §11).
        """
        if week_from > week_to:
            return []
        calendar = AcademicCalendar(
            term.date_of(week_from, 1), term.date_of(week_to, 7), ())
        return self._expand(person, term, week_from, week_to, settings, calendar)

    def _expand(self, person, term, week_from: int, week_to: int, settings,
                calendar: AcademicCalendar | None) -> list[Occurrence]:
        # The person's visible entries expanded with ``calendar`` (built from
        # the database by ``expand_entries`` when None).
        if settings is not None and not settings.show_courses:
            return []
        entries = (TimetableEntry.objects
                   .filter(person=person, term=term, hidden=False)
                   .prefetch_related('overrides').order_by('id'))
        occurrences = expand_entries(entries, term, week_from, week_to, calendar)
        hidden_tags = settings.hidden_tag_set() if settings is not None else set()
        if hidden_tags:
            occurrences = [item for item in occurrences if item.tag not in hidden_tags]
        return occurrences
