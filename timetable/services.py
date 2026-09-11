"""
Domain operations of the timetable app: settings, week view, agenda, term
overview, imports, conflict detection, catalog quick-add and scoped entry
edits. Contract: ``timetable/README.md`` §4.4, §6.5, §8.1–§8.4 and §10.

The API layer calls these functions; nothing here touches credentials — the
portal payload, and the elective 选课结果 page that stands in for an empty
course table, are obtained by the caller through ``pku_account``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any, Callable, Iterable

from django.db import transaction

from app.models import NaturalPerson
from semester.calendar import AcademicCalendar, calendar_between

from timetable.calendar import calendar_for, calendar_payload, day_info, week_days
from timetable.catalog import CatalogIndex
from timetable.config import CONFIG
from timetable.models import (
    OVERRIDE_FIELD_KEYS,
    AcademicTerm,
    CourseCatalogEntry,
    ImportLog,
    TimetableEntry,
    TimetableEntryOverride,
    TimetableSettings,
)
from timetable.overrides import format_time
from timetable.sources import pku_parsers
from timetable.sources.base import (
    DateSpan,
    Occurrence,
    load_sources,
    occurrence_sort_key,
    occurrences_between,
    rule_occurrences,
)
from timetable.sources.pku_parsers import LessonBlock, external_key
from timetable.sources.stored import expand_entries

__all__ = [
    'AGENDA_MAX_DAYS',
    'OVERVIEW_SLOT_KINDS',
    'ROW_ONLY_KEYS',
    'ANNOTATION_KEYS',
    'SCOPES',
    'ImportResult',
    'TimetableImportError',
    'CatalogAddError',
    'get_or_create_settings',
    'settings_payload',
    'person_tags',
    'source_legend',
    'default_term',
    'calendar_for',
    'term_payload',
    'week_view',
    'agenda',
    'describe_weeks',
    'term_overview',
    'elective_results_apply',
    'import_portal',
    'import_text',
    'parse_text',
    'upsert_entries',
    'expand_entries',
    'detect_conflicts',
    'quick_add_from_catalog',
    'update_entry',
]


# Longest agenda one call may return (``README`` §6.5).
AGENDA_MAX_DAYS = 14
# Occurrence kinds that form the weekly slots of the term overview (README
# §10). ``exam`` occurrences are listed separately; every other kind
# (activities, appointments) is a one-off event and left out.
OVERVIEW_SLOT_KINDS = ('course', 'college', 'custom')
_OVERVIEW_EXAM_KIND = 'exam'
# Occurrence ``ref`` keys identifying a lesson across weeks, by preference.
_LESSON_REF_KEYS = ('entry_id', 'course_id')
# Entry keys that only ever live on the row and need ``scope='all'``
# (README §8.2); ``catalog_entry`` is the model name of the API's ``catalog_id``.
ROW_ONLY_KEYS = ('hidden', 'role', 'category', 'catalog_entry')
# Student annotations updated on the row for entries of any source.
ANNOTATION_KEYS = ('hidden', 'color', 'tag', 'role', 'category', 'catalog_entry')
SCOPES = ('all', 'single', 'following')


class TimetableImportError(Exception):
    """An import that could not be applied: unknown format or no lessons."""

    def __init__(self, message: str, code: str = 'PARSE_FAILED'):
        super().__init__(message)
        self.message = message
        self.code = code


class CatalogAddError(Exception):
    """A catalog quick-add that cannot be applied (README §8.1 error codes)."""

    ALREADY_ADDED = 'timetable.catalog_already_added'
    NO_SLOTS = 'timetable.catalog_no_slots'

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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


def person_tags(person) -> list[str]:
    """Distinct non-empty tags of the person's entries, all terms, sorted."""
    tags = (TimetableEntry.objects.filter(person=person).exclude(tag='')
            .values_list('tag', flat=True).distinct())
    return sorted(set(tags))


def source_legend(sources=None, *, with_setting: bool = False) -> list[dict[str, str]]:
    """
    The ``sources`` legend of the API: ``{key, label}`` per loaded source
    (config order), plus ``setting`` — the ``TimetableSettings`` boolean
    toggling the source — when ``with_setting`` (README §8.3).
    """
    if sources is None:
        sources = load_sources()
    legend = []
    for source in sources:
        item = {'key': source.key, 'label': source.label}
        if with_setting:
            item['setting'] = str(getattr(source, 'setting', '') or '')
        legend.append(item)
    return legend


def settings_payload(person,
                     settings: TimetableSettings | None = None) -> dict[str, Any]:
    """
    The ``Settings`` payload of README §4.6 + §8.3: the stored booleans,
    ``hidden_tags``, the source legend with each source's setting name and
    the person's tags.
    """
    if settings is None:
        settings = get_or_create_settings(person)
    return {
        'reminder_enabled': settings.reminder_enabled,
        'reminder_minutes': settings.reminder_minutes,
        'show_courses': settings.show_courses,
        'show_college': settings.show_college,
        'show_activities': settings.show_activities,
        'show_appointments': settings.show_appointments,
        'show_exams': settings.show_exams,
        'share_show_name': settings.share_show_name,
        'hidden_tags': sorted(settings.hidden_tag_set()),
        'sources': source_legend(with_setting=True),
        'tags': person_tags(person),
    }


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
        'exam_week_start': (int(term.exam_week_start)
                            if term.exam_week_start is not None else None),
        'teaching_weeks': term.teaching_weeks,
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
        'sources': source_legend(sources),
    }


def agenda(person, start: date, days: int = 7) -> dict[str, Any]:
    """
    The ``AgendaOut`` payload of ``timetable/README.md`` §6.5: ``days``
    consecutive dates from ``start`` (clamped to ``1..AGENDA_MAX_DAYS``),
    each with the term it belongs to (the active term whose teaching span
    covers it, the latest-starting one when several; ``None`` outside every
    term), its teaching week, its calendar label and the visible occurrences
    of every enabled source. Stored entries need a term and are absent on
    term-less dates; live sources (书院课 activities, applied activities,
    appointments) are date-based and still appear. The legend lists every
    loaded source, as ``week_view`` does.
    """
    days = max(1, min(int(days), AGENDA_MAX_DAYS))
    end = start + timedelta(days=days - 1)
    settings = get_or_create_settings(person)
    span = DateSpan.load(start, end)
    calendar = calendar_between(start, end)
    sources = load_sources()
    occurrences: list[Occurrence] = []
    for source in sources:
        occurrences.extend(occurrences_between(source, person, span, settings))
    occurrences = [item for item in occurrences
                   if not item.hidden and start <= item.date <= end]
    occurrences.sort(key=occurrence_sort_key)
    by_date: dict[date, list[Occurrence]] = {}
    for item in occurrences:
        by_date.setdefault(item.date, []).append(item)
    day_payloads: list[dict[str, Any]] = []
    for on in span.dates():
        term = span.term_of(on)
        info = day_info(on, calendar)
        day_payloads.append({
            'date': on.isoformat(),
            'weekday': on.isoweekday(),
            'term': term.code if term is not None else None,
            'week': term.week_of(on) if term is not None else None,
            'kind': info['kind'],
            'label': info['label'],
            'occurrences': [item.as_dict() for item in by_date.get(on, [])],
        })
    return {
        'from': start.isoformat(),
        'days': day_payloads,
        'sources': source_legend(sources),
    }


def describe_weeks(weeks: Iterable[int]) -> tuple[str, int]:
    """
    ``(weeks_text, parity)`` of a collection of teaching weeks (README §10):
    one week ``第3周``; consecutive weeks ``1-16周``; every other week from an
    odd first week ``1-15周 单周`` (parity 1) or from an even one ``2-16周
    双周`` (parity 2); anything else compressed ranges ``1-8,10-16周`` with
    single weeks as plain numbers. Parity is 0 except for the single/double
    patterns. Duplicates are ignored; no weeks give ``('', 0)``.
    """
    ordered = sorted({int(week) for week in weeks})
    if not ordered:
        return '', 0
    first, last = ordered[0], ordered[-1]
    if len(ordered) == 1:
        return f'第{first}周', 0
    if ordered == list(range(first, last + 1)):
        return f'{first}-{last}周', 0
    if ordered == list(range(first, last + 1, 2)):
        if first % 2 == 1:
            return f'{first}-{last}周 单周', 1
        return f'{first}-{last}周 双周', 2
    runs: list[list[int]] = []
    for week in ordered:
        if runs and week == runs[-1][-1] + 1:
            runs[-1].append(week)
        else:
            runs.append([week])
    parts = [f'{run[0]}-{run[-1]}' if len(run) > 1 else str(run[0]) for run in runs]
    return f'{",".join(parts)}周', 0


def term_overview(person, term: AcademicTerm, *,
                  today: date | None = None) -> dict[str, Any]:
    """
    The ``OverviewOut`` payload of ``timetable/README.md`` §10: every weekly
    slot of the person's timetable over teaching weeks ``1..total_weeks`` of
    ``term`` and the term's exams, for the share poster.

    Every loaded source is asked for its weekly rule
    (``timetable.sources.base.rule_occurrences``) with the person's
    settings, so the ``show_*`` toggles, hidden tags, hidden entries and
    overrides apply as in the week view, while stored entries ignore
    calendar suspensions (holidays and exam periods leave no gap). A
    ``'canceled'`` occurrence (a canceled 书院课 activity) does not count.
    Kinds of ``OVERVIEW_SLOT_KINDS`` are grouped by ``(source, lesson,
    weekday, start, end, location, title)`` — the lesson being
    ``ref['entry_id']``, else ``ref['course_id']``, else the title — with
    their weeks unioned and the other fields taken from the earliest week;
    ``exam`` occurrences are listed once each; other kinds are left out.
    """
    if today is None:
        today = date.today()
    settings = get_or_create_settings(person)
    last_week = max(int(term.total_weeks), 1)
    occurrences: list[Occurrence] = []
    for source in load_sources():
        occurrences.extend(rule_occurrences(source, person, term, 1, last_week, settings))
    occurrences = [item for item in occurrences
                   if not item.hidden and item.status != 'canceled']
    occurrences.sort(key=occurrence_sort_key)
    return {
        'term': term_payload(term, today, calendar=calendar_for(term)),
        'slots': _overview_slots(occurrences),
        'exams': _overview_exams(term, occurrences),
    }


def _lesson_ref(occurrence: Occurrence) -> dict[str, int]:
    # ``{name: id}`` of the reference identifying the occurrence's lesson
    # across weeks (the stored entry, else the 书院课); empty when neither.
    for name in _LESSON_REF_KEYS:
        value = occurrence.ref.get(name)
        if value is not None:
            return {name: value}
    return {}


def _overview_slots(occurrences: list[Occurrence]) -> list[dict[str, Any]]:
    # The ``slots`` of README §10 from date-sorted, already filtered occurrences.
    groups: dict[tuple, list[Occurrence]] = {}
    for item in occurrences:
        if item.kind not in OVERVIEW_SLOT_KINDS:
            continue
        ref = _lesson_ref(item)
        lesson = next(iter(ref.values())) if ref else item.title
        key = (item.source, str(lesson), item.weekday, item.start.strftime('%H:%M'),
               item.end.strftime('%H:%M'), item.location, item.title)
        groups.setdefault(key, []).append(item)
    slots: list[tuple[str, dict[str, Any]]] = []
    for (source, lesson, weekday, start, end, location, title), items in groups.items():
        first = items[0]
        weeks = sorted({item.week for item in items})
        weeks_text, parity = describe_weeks(weeks)
        slots.append((lesson, {
            'key': '',
            'kind': first.kind,
            'source': source,
            'title': title,
            'subtitle': first.subtitle,
            'location': location,
            'weekday': weekday,
            'start': start,
            'end': end,
            'start_section': first.start_section,
            'end_section': first.end_section,
            'weeks': weeks,
            'weeks_text': weeks_text,
            'parity': parity,
            'color_key': first.color_key,
            'role': first.role,
            'tag': first.tag,
            'ref': _lesson_ref(first),
        }))
    slots.sort(key=lambda pair: (
        pair[1]['weekday'], pair[1]['start'], pair[1]['end'], pair[1]['title'],
        pair[1]['weeks'][0], pair[1]['location'], pair[1]['source']))
    counts: dict[tuple[str, str], int] = {}
    result: list[dict[str, Any]] = []
    for lesson, slot in slots:
        index = counts.get((slot['source'], lesson), 0)
        counts[(slot['source'], lesson)] = index + 1
        slot['key'] = f"{slot['source']}:{lesson}:{index}"
        result.append(slot)
    return result


def _overview_exams(term: AcademicTerm,
                    occurrences: list[Occurrence]) -> list[dict[str, Any]]:
    # The ``exams`` of README §10: each exam once, ordered by date and time.
    exams: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for item in occurrences:
        if item.kind != _OVERVIEW_EXAM_KIND:
            continue
        exam = {
            'title': item.title,
            'date': item.date.isoformat(),
            'start': item.start.strftime('%H:%M'),
            'end': item.end.strftime('%H:%M'),
            'location': item.location,
            'week': item.week if term.contains_week(item.week) else None,
        }
        key = (exam['date'], exam['start'], exam['end'], exam['title'], exam['location'])
        exams.setdefault(key, exam)
    return [exams[key] for key in sorted(exams)]


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


# Longest note stored from an import or the API (README §8.1).
NOTE_MAX_LENGTH = 2000
_CATALOG_FILL_KEYS = ('teacher', 'course_code', 'class_no')


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
        'note': (block.note or '')[:NOTE_MAX_LENGTH],
        'raw_text': block.raw or '',
        **_exam_fields(block),
    }


def _exam_fields(block: LessonBlock) -> dict[str, Any]:
    # The block's 考试信息 as stored (README §8.4); all blank without a valid date.
    exam_date = None
    if block.exam_date:
        try:
            exam_date = date.fromisoformat(str(block.exam_date))
        except ValueError:
            exam_date = None
    if exam_date is None:
        return {'exam_date': None, 'exam_period': '', 'exam_room': ''}
    period = str(block.exam_period or '')
    if period not in TimetableEntry.ExamPeriod.values:
        period = ''
    return {
        'exam_date': exam_date,
        'exam_period': period,
        'exam_room': str(block.exam_room or '')[:100],
    }


def _link_catalog(fields: dict[str, Any], index: CatalogIndex) -> None:
    # Point the block at its catalog row (README §8.1) and fill blank
    # teacher/course_code/class_no from it; the student's own non-blank
    # values are never overwritten.
    row = index.match(course_code=fields['course_code'], class_no=fields['class_no'],
                      name=fields['name'], teacher=fields['teacher'])
    fields['catalog_entry'] = row
    if row is None:
        return
    for name in _CATALOG_FILL_KEYS:
        if not fields[name]:
            max_length = TimetableEntry._meta.get_field(name).max_length
            fields[name] = (getattr(row, name) or '')[:max_length]


def _log_failure(person, term, source, message: str) -> ImportLog:
    return ImportLog.objects.create(
        person=person, term=term, source=source,
        status=ImportLog.Status.FAILED, entries_count=0, message=message[:1000])


def upsert_entries(person, term: AcademicTerm, source, blocks: Iterable[LessonBlock], *,
                   note: str = '') -> ImportResult:
    """
    Replace the person's entries of ``source`` in ``term`` with ``blocks``:
    upsert on ``external_key`` and delete entries of that source that
    disappeared. The student's annotations — ``hidden``, ``color``,
    ``tag``, ``role``, ``category``, an existing ``catalog_entry`` and the
    override rows — survive an update; imported fields, the exam info of
    §8.4 included, are refreshed. Every block is matched against the
    course catalog (§8.1): a new entry, or one not linked yet, gets
    ``catalog_entry`` and blank teacher/course_code/class_no filled from
    the row. Other sources and other terms are untouched. Blocks that
    cannot be placed (bad weekday/sections) are skipped and counted in the
    log; ``note`` opens the log message.
    """
    source = TimetableEntry.Source(source)
    if source == TimetableEntry.Source.MANUAL:
        raise ValueError('manual entries are not imported')
    prepared: dict[str, dict[str, Any]] = {}
    skipped = 0
    index: CatalogIndex | None = None
    for block in blocks:
        fields = _entry_fields(term, block)
        if fields is None:
            skipped += 1
            continue
        if index is None:
            index = CatalogIndex.for_term(term)
        _link_catalog(fields, index)
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
                if entry.catalog_entry_id is not None:
                    # Keep the link the student (or an earlier import) chose.
                    fields = {name: value for name, value in fields.items()
                              if name != 'catalog_entry'}
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
        parts = [note] if note else []
        if skipped:
            parts.append(f'skipped {skipped} block(s) that could not be placed')
        log = ImportLog.objects.create(
            person=person, term=term, source=source,
            status=ImportLog.Status.OK, entries_count=len(entries),
            message='; '.join(parts))
    entries.sort(key=lambda entry: (
        entry.weekday, entry.start_section, entry.start_time, entry.pk))
    return ImportResult(created, updated, removed, entries, log)


def elective_results_apply(term: AcademicTerm, on: date | None = None) -> bool:
    """
    Whether the elective 选课结果 page may stand in for an empty portal
    course table of ``term``: the term's span covers ``on`` (today by
    default) or it is the next active term to start. The page shows the
    selection in progress, which is never that of a finished term.
    """
    if on is None:
        on = date.today()
    if term.covers(on):
        return True
    upcoming = AcademicTerm.upcoming(on)
    return upcoming is not None and upcoming.pk == term.pk


def import_portal(person, term: AcademicTerm, raw_json, *,
                  elective_results: Callable[[], tuple[str | None, str]] | None = None,
                  today: date | None = None) -> ImportResult:
    """
    Parse a portal ``getCourseInfo.do`` payload and store it as source
    ``portal``.

    When the payload yields no lessons (an empty table, or no course table
    at all) and ``elective_results`` is given for a term where
    ``elective_results_apply(term, today)``, the callable is asked for the
    elective 选课结果 page as ``(html or None, outcome)``; it does the
    network I/O (no transaction is open) and ``outcome`` is a short tag of
    what happened. The page's lessons are stored under the same source
    ``portal``, so a later course-table import replaces them, and the
    ``ImportLog`` message records the fallback.

    Raises ``TimetableImportError`` (after writing a failed ``ImportLog``
    that names the fallback outcome) when no lessons could be stored; the
    stored entries are left untouched in that case.
    """
    source = TimetableEntry.Source.PORTAL
    parse_error: ValueError | None = None
    try:
        blocks = pku_parsers.parse_portal_course_json(raw_json)
    except ValueError as exc:
        parse_error = exc
        blocks = []
        problem = f'parse error: {exc}'
        message = f'门户课表解析失败：{exc}'
    else:
        problem = 'no lessons in portal payload'
        message = '门户未返回任何课程，本地课表未改动'
    if blocks:
        return upsert_entries(person, term, source, blocks)
    if elective_results is not None and elective_results_apply(term, today):
        html, outcome = elective_results()
        fallback = pku_parsers.parse_elective_table(html) if html else []
        if fallback:
            return upsert_entries(person, term, source, fallback,
                                  note=f'{problem}; imported from elective results')
        detail = outcome if html is None else 'no lessons in elective results'
        problem = f'{problem}; elective fallback: {detail}'
    _log_failure(person, term, source, problem)
    raise TimetableImportError(message) from parse_error


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


# ---------------------------------------------------------------------------
# catalog quick-add (README §8.1)
# ---------------------------------------------------------------------------

def _slot_fields(term: AcademicTerm, slot: Any) -> dict[str, Any] | None:
    # Stored field values of one catalog slot, or None when it cannot be
    # placed in ``term``.
    if not isinstance(slot, dict):
        return None
    try:
        weekday = int(slot.get('weekday', 0))
        start_section = int(slot.get('start_section', 0))
        end_section = int(slot.get('end_section', 0))
        week_start = int(slot.get('week_start', 1))
        week_end = int(slot.get('week_end', term.teaching_weeks))
        parity = int(slot.get('parity', 0))
    except (TypeError, ValueError):
        return None
    if not 1 <= weekday <= 7 or start_section < 1 or end_section < start_section:
        return None
    start = term.section_time(start_section)
    end = term.section_time(end_section)
    if start is None or end is None:
        return None
    week_end = max(1, min(week_end, int(term.total_weeks)))
    week_start = max(1, min(week_start, week_end))
    return {
        'room': str(slot.get('room') or '')[:100],
        'weekday': weekday,
        'start_section': start_section,
        'end_section': end_section,
        'start_time': start[0],
        'end_time': end[1],
        'week_start': week_start,
        'week_end': week_end,
        'parity': parity if parity in (0, 1, 2) else 0,
    }


def quick_add_from_catalog(person, term: AcademicTerm, row: CourseCatalogEntry, *,
                           role: str = TimetableEntry.Role.AUDIT,
                           slot_indices: Iterable[int] | None = None,
                           ) -> list[TimetableEntry]:
    """
    Add a catalog row to the person's timetable of ``term``: one manual
    entry per selected slot (indices into ``row.slots``; all by default),
    linked to the row, ``category='course'``, name/code/class/teacher and
    the slot's room/weekday/sections/weeks/parity copied. Week ranges are
    clamped to the term. Raises ``CatalogAddError`` (``ALREADY_ADDED`` when
    the person already has an entry of the term linked to the row,
    ``NO_SLOTS`` when no selected slot can be placed) and ``ValueError``
    listing out-of-range indices. Atomic per person.
    """
    slots = row.slots if isinstance(row.slots, list) else []
    if not slots:
        raise CatalogAddError(CatalogAddError.NO_SLOTS, f'「{row.name}」没有可用的上课时间')
    if slot_indices is None:
        indices = list(range(len(slots)))
    else:
        indices = [int(index) for index in slot_indices]
        bad = sorted({index for index in indices if not 0 <= index < len(slots)})
        if bad:
            raise ValueError(f'slot index out of range: {", ".join(map(str, bad))}')
        indices = sorted(set(indices))
    prepared = [fields for fields in (_slot_fields(term, slots[index])
                                      for index in indices)
                if fields is not None]
    if not prepared:
        raise CatalogAddError(CatalogAddError.NO_SLOTS, f'「{row.name}」没有可用的上课时间')
    role = TimetableEntry.Role(role)
    with transaction.atomic():
        NaturalPerson.objects.select_for_update().get(pk=person.pk)
        linked = TimetableEntry.objects.filter(
            person=person, term=term, catalog_entry=row)
        if linked.exists():
            raise CatalogAddError(CatalogAddError.ALREADY_ADDED, f'「{row.name}」已经在课表中')
        entries = [
            TimetableEntry.objects.create(
                person=person, term=term, source=TimetableEntry.Source.MANUAL,
                external_key=TimetableEntry.new_manual_key(),
                catalog_entry=row, role=role, category=TimetableEntry.Category.COURSE,
                name=row.name[:100], course_code=row.course_code[:32],
                class_no=row.class_no[:16], teacher=row.teacher[:100],
                raw_text='', **fields)
            for fields in prepared
        ]
    return entries


# ---------------------------------------------------------------------------
# scoped edits (README §8.2)
# ---------------------------------------------------------------------------

def _override_json(name: str, value: Any) -> Any:
    # JSON value of an override field: times as 'HH:MM', the rest as given.
    if isinstance(value, time):
        return format_time(value)
    if value is None:
        return ''
    return value


def update_entry(entry: TimetableEntry, values: dict[str, Any], *,
                 scope: str = 'all', week: int | None = None,
                 canceled: bool | None = None) -> TimetableEntry:
    """
    Apply an edit to ``entry`` (README §8.2). ``values`` map model field
    names (``catalog_entry`` for the API's ``catalog_id``) to validated
    values.

    - ``scope='all'``: a manual entry's row takes every value; for imported
      entries the annotations (``ANNOTATION_KEYS``) go to the row and the
      other override keys are merged into the whole-range override
      (``week_start=week_end=None``, created on demand). ``canceled`` is
      not allowed.
    - ``scope='single'`` / ``'following'``: ``week`` must lie in the
      entry's span; the override ``(week, week)`` / ``(week, None)`` is
      upserted with the given override keys and ``canceled``.

    ``ValueError`` names a key that is not allowed for the scope/source
    (the API validates first and answers 400). Atomic; returns the entry.
    """
    if scope not in SCOPES:
        raise ValueError(f'unknown scope {scope!r}')
    if scope != 'all':
        if week is None or not entry.contains_week(int(week)):
            raise ValueError('week must lie in the entry\'s week range')
        week = int(week)
    elif canceled is not None:
        raise ValueError('canceled needs scope single or following')
    row_values: dict[str, Any] = {}
    override_values: dict[str, Any] = {}
    for name, value in values.items():
        if scope == 'all' and (entry.is_manual() or name in ANNOTATION_KEYS):
            row_values[name] = value
        elif name in OVERRIDE_FIELD_KEYS:
            override_values[name] = value
        else:
            raise ValueError(f'{name} cannot be changed with scope {scope!r}')
    if scope == 'all':
        bounds: tuple[int | None, int | None] = (None, None)
    elif scope == 'single':
        bounds = (week, week)
    else:
        bounds = (week, None)
    with transaction.atomic():
        if row_values:
            for name, value in row_values.items():
                setattr(entry, name, value)
            entry.save(update_fields=list(row_values) + ['updated_at'])
        if override_values or canceled is not None:
            override = (TimetableEntryOverride.objects.select_for_update()
                        .filter(entry=entry, week_start=bounds[0], week_end=bounds[1])
                        .order_by('id').first())
            if override is None:
                override = TimetableEntryOverride(
                    entry=entry, week_start=bounds[0], week_end=bounds[1])
            fields = dict(override.fields) if isinstance(override.fields, dict) else {}
            for name, value in override_values.items():
                fields[name] = _override_json(name, value)
            override.fields = fields
            if canceled is not None:
                override.canceled = bool(canceled)
            override.save()
    return entry
