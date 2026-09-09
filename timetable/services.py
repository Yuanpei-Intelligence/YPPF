"""
Domain operations of the timetable app: settings, week view, imports and
conflict detection. Contract: ``timetable/README.md`` §4.4.

The API layer calls these functions; nothing here touches credentials — the
portal payload is obtained by the caller through ``pku_account``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from django.db import transaction

from app.models import NaturalPerson
from semester.calendar import AcademicCalendar

from timetable.calendar import calendar_for, calendar_payload, week_days
from timetable.config import CONFIG
from timetable.models import (
    AcademicTerm,
    ImportLog,
    TimetableEntry,
    TimetableSettings,
)
from timetable.sources import pku_parsers
from timetable.sources.base import Occurrence, load_sources, occurrence_sort_key
from timetable.sources.pku_parsers import LessonBlock, external_key
from timetable.sources.stored import expand_entries

__all__ = [
    'ImportResult',
    'TimetableImportError',
    'get_or_create_settings',
    'default_term',
    'calendar_for',
    'term_payload',
    'week_view',
    'import_portal',
    'import_text',
    'parse_text',
    'upsert_entries',
    'expand_entries',
    'detect_conflicts',
]


class TimetableImportError(Exception):
    """An import that could not be applied: unknown format or no lessons."""

    def __init__(self, message: str, code: str = 'PARSE_FAILED'):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ImportResult:
    """Outcome of ``upsert_entries``: counts, the surviving entries, the log."""

    created: int
    updated: int
    removed: int
    entries: list[TimetableEntry]
    log: ImportLog

    @property
    def total(self) -> int:
        return len(self.entries)


parse_text = pku_parsers.parse_text


def get_or_create_settings(person) -> TimetableSettings:
    """The person's ``TimetableSettings`` row, created with config defaults."""
    settings, _ = TimetableSettings.objects.get_or_create(
        person=person,
        defaults={'reminder_minutes': CONFIG.reminder_default_minutes})
    return settings


def default_term(on: date | None = None) -> AcademicTerm | None:
    """
    The term to show by default: the current term, or — before the first
    term of the year starts — the next active term; ``None`` if none.
    """
    return AcademicTerm.current(on) or AcademicTerm.upcoming(on)


def term_payload(term: AcademicTerm, on: date | None = None, *,
                 calendar: AcademicCalendar | None = None) -> dict[str, Any]:
    """
    JSON shape of ``Term`` in ``timetable/README.md`` §4.6 (+ ``calendar``,
    §6.4: the university calendar events overlapping the term's teaching
    weeks). Pass the term's ``calendar`` (``calendar_for``) to save a query.
    """
    if on is None:
        on = date.today()
    if calendar is None:
        calendar = calendar_for(term)
    week = term.week_of(on)
    return {
        'code': term.code,
        'name': term.name,
        'week1_monday': term.week1_monday.isoformat(),
        'total_weeks': term.total_weeks,
        'current_week': week if term.contains_week(week) else None,
        'section_times': term.section_times,
        'calendar': calendar_payload(calendar),
    }


def week_view(person, term: AcademicTerm, week: int, *,
              today: date | None = None) -> dict[str, Any]:
    """
    The ``WeekView`` payload of ``timetable/README.md`` §4.6 for one
    teaching week (clamped to ``1..total_weeks``): occurrences of every
    enabled source, conflicts, the legend and the calendar label of each
    day (§6.4). Stored-entry sources already follow the calendar (no
    occurrences on holiday/exam dates, swapped weekdays), live sources
    are real events and are left as they are.
    """
    if today is None:
        today = date.today()
    week = term.clamp_week(week)
    settings = get_or_create_settings(person)
    calendar = calendar_for(term)
    sources = load_sources()
    occurrences: list[Occurrence] = []
    for source in sources:
        occurrences.extend(source.occurrences(person, term, week, week, settings))
    occurrences = [item for item in occurrences if not item.hidden]
    occurrences.sort(key=occurrence_sort_key)
    today_week = term.week_of(today)
    return {
        'term': term_payload(term, today, calendar=calendar),
        'week': week,
        'week_dates': [day.isoformat() for day in term.week_dates(week)],
        'days': week_days(term, week, calendar),
        'today': {
            'date': today.isoformat(),
            'weekday': today.isoweekday(),
            'week': today_week if term.contains_week(today_week) else None,
        },
        'occurrences': [item.as_dict() for item in occurrences],
        'conflicts': detect_conflicts(occurrences),
        'sources': [{'key': source.key, 'label': source.label} for source in sources],
    }


def detect_conflicts(occurrences: Iterable[Occurrence]) -> list[list[str]]:
    """
    Groups of ids of occurrences that overlap in time on the same date.
    Hidden and canceled occurrences are ignored. Overlap is transitive within a group
    (A–B and B–C overlapping put A, B, C in one group).
    """
    by_date: dict[date, list[Occurrence]] = {}
    for item in occurrences:
        if item.hidden or item.status == 'canceled':
            continue
        by_date.setdefault(item.date, []).append(item)
    groups: list[list[str]] = []
    for on in sorted(by_date):
        current: list[Occurrence] = []
        current_end = None
        for item in sorted(by_date[on], key=occurrence_sort_key):
            if current and current_end is not None and item.start < current_end:
                current.append(item)
                current_end = max(current_end, item.end)
                continue
            if len(current) > 1:
                groups.append([member.id for member in current])
            current = [item]
            current_end = item.end
        if len(current) > 1:
            groups.append([member.id for member in current])
    return groups


def _entry_fields(term: AcademicTerm, block: LessonBlock) -> dict[str, Any] | None:
    # Stored field values of a block, or None when it cannot be placed.
    weekday = int(block.weekday)
    start_section = int(block.start_section)
    end_section = int(block.end_section)
    if not 1 <= weekday <= 7 or start_section < 1 or end_section < start_section:
        return None
    start = term.section_time(start_section)
    end = term.section_time(end_section)
    if start is None or end is None:
        return None
    week_start = max(1, int(block.week_start))
    week_end = max(week_start, int(block.week_end))
    parity = int(block.parity) if int(block.parity) in (0, 1, 2) else 0
    name = (block.name or '').strip()
    if not name:
        return None
    return {
        'name': name[:100],
        'course_code': (block.course_code or '')[:32],
        'class_no': (block.class_no or '')[:16],
        'teacher': (block.teacher or '')[:100],
        'room': (block.room or '')[:100],
        'weekday': weekday,
        'start_section': start_section,
        'end_section': end_section,
        'start_time': start[0],
        'end_time': end[1],
        'week_start': week_start,
        'week_end': week_end,
        'parity': parity,
        'note': (block.note or '')[:200],
        'raw_text': block.raw or '',
    }


def _log_failure(person, term, source, message: str) -> ImportLog:
    return ImportLog.objects.create(
        person=person, term=term, source=source,
        status=ImportLog.Status.FAILED, entries_count=0, message=message[:1000])


def upsert_entries(person, term: AcademicTerm, source, blocks: Iterable[LessonBlock]) -> ImportResult:
    """
    Replace the person's entries of ``source`` in ``term`` with ``blocks``:
    upsert on ``external_key`` (user customisations ``hidden``/``color``
    survive an update) and delete entries of that source that disappeared.
    Other sources and other terms are untouched. Blocks that cannot be
    placed (bad weekday/sections) are skipped and counted in the log.
    """
    source = TimetableEntry.Source(source)
    if source == TimetableEntry.Source.MANUAL:
        raise ValueError('manual entries are not imported')
    prepared: dict[str, dict[str, Any]] = {}
    skipped = 0
    for block in blocks:
        fields = _entry_fields(term, block)
        if fields is None:
            skipped += 1
            continue
        prepared.setdefault(external_key(block), fields)
    with transaction.atomic():
        # Serialize imports of one person: a first import has no entry rows
        # to lock, so two concurrent imports would otherwise race on the
        # unique key and surface an IntegrityError.
        NaturalPerson.objects.select_for_update().get(pk=person.pk)
        existing = {
            entry.external_key: entry
            for entry in TimetableEntry.objects.select_for_update()
            .filter(person=person, term=term, source=source).order_by('id')
        }
        created = updated = 0
        entries: list[TimetableEntry] = []
        for key, fields in prepared.items():
            entry = existing.pop(key, None)
            if entry is None:
                entry = TimetableEntry.objects.create(
                    person=person, term=term, source=source,
                    external_key=key, **fields)
                created += 1
            else:
                changed = [name for name, value in fields.items()
                           if getattr(entry, name) != value]
                if changed:
                    for name in changed:
                        setattr(entry, name, fields[name])
                    entry.save(update_fields=changed + ['updated_at'])
                    updated += 1
            entries.append(entry)
        removed = 0
        if existing:
            _, deleted = TimetableEntry.objects.filter(
                pk__in=[entry.pk for entry in existing.values()]).delete()
            removed = deleted.get(TimetableEntry._meta.label, 0)
        message = f'skipped {skipped} block(s) that could not be placed' if skipped else ''
        log = ImportLog.objects.create(
            person=person, term=term, source=source,
            status=ImportLog.Status.OK, entries_count=len(entries),
            message=message)
    entries.sort(key=lambda entry: (
        entry.weekday, entry.start_section, entry.start_time, entry.pk))
    return ImportResult(created, updated, removed, entries, log)


def import_portal(person, term: AcademicTerm, raw_json) -> ImportResult:
    """
    Parse a portal ``getCourseInfo.do`` payload and store it as source
    ``portal``. Raises ``TimetableImportError`` (after writing a failed
    ``ImportLog``) when the payload is not a course table or holds no
    lessons; the stored entries are left untouched in that case.
    """
    source = TimetableEntry.Source.PORTAL
    try:
        blocks = pku_parsers.parse_portal_course_json(raw_json)
    except ValueError as exc:
        _log_failure(person, term, source, f'parse error: {exc}')
        raise TimetableImportError(f'门户课表解析失败：{exc}') from exc
    if not blocks:
        _log_failure(person, term, source, 'no lessons in portal payload')
        raise TimetableImportError('门户未返回任何课程，本地课表未改动')
    return upsert_entries(person, term, source, blocks)


def import_text(person, term: AcademicTerm, text: str, *,
                dry_run: bool = False) -> ImportResult | list[LessonBlock]:
    """
    Parse pasted text (portal HTML, elective table, plain text) and store it
    as source ``paste``. With ``dry_run`` only the parsed blocks are
    returned and nothing is written. Raises ``TimetableImportError`` (after
    writing a failed ``ImportLog``) when nothing could be parsed.
    """
    fmt, blocks = pku_parsers.parse_text(text)
    if dry_run:
        return blocks
    source = TimetableEntry.Source.PASTE
    if fmt == 'unknown':
        _log_failure(person, term, source, 'unknown format')
        raise TimetableImportError('无法识别课表格式，请检查粘贴的内容')
    if not blocks:
        _log_failure(person, term, source, f'no lessons parsed ({fmt})')
        raise TimetableImportError('未从粘贴内容中解析到任何课程')
    return upsert_entries(person, term, source, blocks)
