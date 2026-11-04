"""
Course catalog (``timetable/README.md`` §6.3, §8.1): best-effort parsing of
the 起止周 / 上课时间 columns into timetable slots, upsert of imported rows,
the search behind ``GET /api/v2/timetable/catalog/`` and the matching that
links imported timetable entries to catalog rows.

Rows come from the PKU-Course-Crawler workbook through the
``import_course_catalog`` command; the parsers here are pure functions so
they can be exercised without a database.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q, QuerySet

from timetable.models import AcademicTerm, CourseCatalogEntry
from timetable.sources.pku_parsers import parse_time_pieces, parse_week_spec

__all__ = [
    'SLOT_KEYS',
    'DEFAULT_WEEKS',
    'MAX_SEARCH_LIMIT',
    'COURSE_CODE_DIGITS',
    'CLASS_NO_DIGITS',
    'parse_catalog_slots',
    'parse_credits',
    'parse_term_code',
    'normalise_catalog_row',
    'upsert_catalog_rows',
    'search_catalog',
    'normalise_course_code',
    'normalise_class_no',
    'normalise_name',
    'CatalogIndex',
    'match_catalog',
]

# Numeric course codes / class numbers are zero-padded to these widths
# (the university's format; ``import_course_catalog`` does the same).
COURSE_CODE_DIGITS = 8
CLASS_NO_DIGITS = 2

SLOT_KEYS = ('weekday', 'start_section', 'end_section', 'week_start',
             'week_end', 'parity', 'room')
DEFAULT_WEEKS = (1, 16)
MAX_SEARCH_LIMIT = 100
MAX_SECTION = 20
MAX_WEEK = 30

_TEXT_FIELDS = (
    'department', 'course_code', 'name', 'name_en', 'class_no', 'audience',
    'category', 'hours_per_week', 'total_hours', 'teacher', 'weeks_text',
    'time_text', 'note',
)
_MERGE_APPEND_FIELDS = ('weeks_text', 'time_text')

_WEEKDAY_TOKENS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 7, '天': 7,
    '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
}
_SPACES_RE = re.compile(r'[ \t　\xa0]+')
_PIECE_SPLIT_RE = re.compile(r'[;；|\n\r]+')
# '1-16' / '1~16' without the 周 marker: the 起止周 column is often bare.
_BARE_WEEK_RANGE_RE = re.compile(r'(?<!\d)(\d{1,2})\s*[-~～－—–至]\s*(\d{1,2})(?!\d)')
# '周二3-4节 理教201', '星期二 第3~4节', '周2 3-4'; the room runs to the
# next weekday token (one that is followed by a section number) or the end.
_WEEKDAY_TOKEN = r'(?:周|星期|礼拜)\s*([一二三四五六日天1-7])'
_NEXT_SLOT_LOOKAHEAD = r'(?=(?:周|星期|礼拜)\s*[一二三四五六日天1-7]\s*[:：]?\s*第?\s*\d|$)'
_CATALOG_TIME_RE = re.compile(
    _WEEKDAY_TOKEN + r'\s*[:：]?\s*第?\s*(\d{1,2})\s*(?:[-~～－—–至]\s*(\d{1,2}))?\s*节?'
    r'[ \t　\xa0]*(.*?)\s*' + _NEXT_SLOT_LOOKAHEAD,
    re.DOTALL)
_WEEK_SPEC_RE = re.compile(r'(?<!\d)\d{1,2}\s*(?:[-~～－—–至]\s*\d{1,2})?\s*周')
_PARITY_WORD_RE = re.compile(r'每周|单周|双周')
_EMPTY_BRACKETS_RE = re.compile(r'[（(]\s*[)）]')
_SEPARATOR_RE = re.compile(r'[,，;；、|]')
_CREDITS_RE = re.compile(r'\d+(?:\.\d+)?')
_TERM_SUFFIX_BY_WORD = {
    '1': '1', '一': '1', '秋': '1',
    '2': '2', '二': '2', '春': '2',
    '3': '3', '三': '3', '夏': '3',
}
# '2026-2027学年第一学期', '26-27学年第1学期', '26-27-1', '2026-2027学年秋季学期'.
# Four-digit years are tried first so '2026-2027' is not read as '20' + '26'.
_TERM_TEXT_RE = re.compile(
    r'(?<!\d)(\d{4}|\d{2})\s*[-–~～－—/至]\s*(\d{4}|\d{2})(?!\d)\s*(?:学年度?)?\s*'
    r'(?:[-–~～－—/]\s*|第\s*)?([123一二三秋春夏])\s*(?:季|学期|季学期)?')


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def _clean_room(text: str) -> str:
    # The room is what remains of a time piece after week ranges, parity
    # words, separators and empty brackets are removed.
    text = _WEEK_SPEC_RE.sub(' ', text or '')
    text = _PARITY_WORD_RE.sub(' ', text)
    text = _EMPTY_BRACKETS_RE.sub(' ', text)
    text = _SEPARATOR_RE.sub(' ', text)
    return _SPACES_RE.sub(' ', text).strip()


def _week_ranges(text: str) -> tuple[list[tuple[int, int]], int]:
    # Ranges with the 周 marker first; a bare '1-16' second.
    ranges, parity = parse_week_spec(text)
    if not ranges:
        for start, end in _BARE_WEEK_RANGE_RE.findall(text or ''):
            week_start, week_end = int(start), int(end)
            if week_end < week_start:
                week_start, week_end = week_end, week_start
            ranges.append((week_start, week_end))
    return ranges, parity


def _slot(weekday: int, start_section: int, end_section: int,
          week_start: int, week_end: int, parity: int,
          room: str) -> dict[str, Any] | None:
    if end_section < start_section:
        start_section, end_section = end_section, start_section
    if week_end < week_start:
        week_start, week_end = week_end, week_start
    if not 1 <= weekday <= 7:
        return None
    if not 1 <= start_section <= end_section <= MAX_SECTION:
        return None
    if not 1 <= week_start <= week_end <= MAX_WEEK:
        return None
    return {
        'weekday': weekday,
        'start_section': start_section,
        'end_section': end_section,
        'week_start': week_start,
        'week_end': week_end,
        'parity': parity if parity in (0, 1, 2) else 0,
        'room': room,
    }


def parse_catalog_slots(
    weeks_text: str, time_text: str, *,
    default_weeks: tuple[int, int] = DEFAULT_WEEKS,
) -> list[dict[str, Any]]:
    """
    Best-effort parse of the 起止周 and 上课时间 columns into slots
    (dicts with ``SLOT_KEYS``).

    ``weeks_text`` accepts ``1-16周``, ``1~16周``, a bare ``1-16``, several
    ranges and 每周/单周/双周. ``time_text`` holds one or more pieces
    separated by ``;``/``；``/newline such as ``周二3-4节 理教201``,
    ``周二3~4节``, ``星期二 第3-4节``, an elective-style
    ``1~16周 每周周二1~2节 理教306`` (which carries its own weeks) or a
    piece prefixed with its own week range (``9-16周 周四5-6节``). Week
    ranges of a piece override ``weeks_text``; ``default_weeks`` is used
    when neither gives a range. Unparseable pieces are dropped.
    """
    default_ranges, default_parity = _week_ranges(weeks_text)
    if not default_ranges:
        default_ranges = [tuple(default_weeks)]
    slots: list[dict[str, Any]] = []
    for piece in _PIECE_SPLIT_RE.split(time_text or ''):
        piece = piece.strip()
        if not piece:
            continue
        candidates: list[dict[str, Any] | None] = []
        elective = parse_time_pieces(piece)
        if elective:
            for item in elective:
                candidates.append(_slot(
                    item['weekday'], item['start_section'], item['end_section'],
                    item['week_start'], item['week_end'], item['parity'],
                    _clean_room(item['room'])))
        else:
            ranges, parity = parse_week_spec(piece)
            if not ranges:
                ranges = default_ranges
            if parity == 0:
                parity = default_parity
            for match in _CATALOG_TIME_RE.finditer(piece):
                weekday_token, start, end, room = match.groups()
                start_section = int(start)
                end_section = int(end) if end else start_section
                for week_start, week_end in ranges:
                    candidates.append(_slot(
                        _WEEKDAY_TOKENS[weekday_token], start_section, end_section,
                        week_start, week_end, parity, _clean_room(room)))
        for slot in candidates:
            if slot is not None and slot not in slots:
                slots.append(slot)
    return slots


def parse_credits(value: Any) -> Decimal | None:
    """
    ``参考学分`` as a one-decimal ``Decimal`` (``'2'``, ``2.5``, ``'3学分'``);
    ``None`` when absent or not a number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        match = _CREDITS_RE.search(str(value))
        if match is None:
            return None
        text = match.group(0)
    try:
        credits = Decimal(text)
    except InvalidOperation:
        return None
    if not credits.is_finite() or credits < 0 or credits >= 1000:
        return None
    return credits.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def parse_term_code(text: Any) -> str | None:
    """
    An ``AcademicTerm.code`` (``'26-27-1'``) from a 学年学期 cell such as
    ``2026-2027学年第一学期``, ``26-27学年第1学期``, ``2026-2027学年秋季学期``
    or ``26-27-1``; ``None`` when the text is not recognised.
    """
    if text is None:
        return None
    match = _TERM_TEXT_RE.search(_SPACES_RE.sub('', str(text)))
    if match is None:
        return None
    first, second, suffix = match.groups()
    first, second = first[-2:], second[-2:]
    if (int(second) - int(first)) % 100 != 1:
        return None
    return f'{first}-{second}-{_TERM_SUFFIX_BY_WORD[suffix]}'


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    return _SPACES_RE.sub(' ', text).strip()


def normalise_catalog_row(
    row: dict[str, Any], *,
    default_weeks: tuple[int, int] = DEFAULT_WEEKS,
) -> dict[str, Any] | None:
    """
    Model field values of one imported row (keys named after the model
    fields; ``slots`` is parsed from ``weeks_text``/``time_text`` unless
    given). Text is trimmed to the column lengths. ``None`` when the row
    has no ``course_code`` or ``name`` and therefore cannot be keyed.
    """
    fields: dict[str, Any] = {}
    for name in _TEXT_FIELDS:
        max_length = CourseCatalogEntry._meta.get_field(name).max_length
        fields[name] = _text(row.get(name))[:max_length]
    if not fields['course_code'] or not fields['name']:
        return None
    fields['credits'] = parse_credits(row.get('credits'))
    slots = row.get('slots')
    if slots is None:
        slots = parse_catalog_slots(
            fields['weeks_text'], fields['time_text'], default_weeks=default_weeks)
    fields['slots'] = list(slots)
    return fields


def _merge_row(current: dict[str, Any], extra: dict[str, Any]) -> None:
    # A second row of the same (course_code, class_no): blanks are filled,
    # time columns are appended, slots are unioned.
    for name in _TEXT_FIELDS:
        if name in _MERGE_APPEND_FIELDS:
            if extra[name] and extra[name] not in current[name]:
                max_length = CourseCatalogEntry._meta.get_field(name).max_length
                joined = extra[name]
                if current[name]:
                    joined = f'{current[name]};{extra[name]}'
                current[name] = joined[:max_length]
        elif not current[name] and extra[name]:
            current[name] = extra[name]
    if current['credits'] is None:
        current['credits'] = extra['credits']
    for slot in extra['slots']:
        if slot not in current['slots']:
            current['slots'].append(slot)


def upsert_catalog_rows(term: AcademicTerm,
                        rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """
    Upsert catalog rows of ``term`` keyed by ``(course_code, class_no)``.

    ``rows`` are dicts with the model's field names (see
    ``normalise_catalog_row``). Rows without ``course_code``/``name`` are
    skipped; several rows of one key are merged (later rows fill blanks and
    add time pieces). Existing rows of other keys are kept, so the command
    can be re-run and can import a workbook in parts. Returns
    ``(created, updated)``.
    """
    # A row without a week range spans the teaching weeks, not the exam
    # weeks (README §8.4).
    default_weeks = (1, max(int(term.teaching_weeks), 1))
    prepared: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        fields = normalise_catalog_row(row, default_weeks=default_weeks)
        if fields is None:
            continue
        key = (fields['course_code'], fields['class_no'])
        current = prepared.get(key)
        if current is None:
            prepared[key] = fields
        else:
            _merge_row(current, fields)
    created = updated = 0
    with transaction.atomic():
        existing = {
            (entry.course_code, entry.class_no): entry
            for entry in CourseCatalogEntry.objects.select_for_update()
            .filter(term=term).order_by('id')
        }
        to_create: list[CourseCatalogEntry] = []
        for key, fields in prepared.items():
            entry = existing.get(key)
            if entry is None:
                to_create.append(CourseCatalogEntry(term=term, **fields))
                continue
            changed = [name for name, value in fields.items()
                       if getattr(entry, name) != value]
            if changed:
                for name in changed:
                    setattr(entry, name, fields[name])
                entry.save(update_fields=changed)
                updated += 1
        if to_create:
            CourseCatalogEntry.objects.bulk_create(to_create, batch_size=500)
            created = len(to_create)
    return created, updated


def search_catalog(term: AcademicTerm, q: str,
                   limit: int = 20) -> QuerySet[CourseCatalogEntry]:
    """
    Up to ``limit`` catalog rows of ``term`` whose name, English name,
    course code or teacher contains ``q`` (case-insensitive), ordered by
    course code and class number. A blank ``q`` matches nothing.
    """
    q = _SPACES_RE.sub(' ', q or '').strip()
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    if not q:
        return CourseCatalogEntry.objects.none()
    return (
        CourseCatalogEntry.objects.filter(term=term)
        .filter(Q(name__icontains=q) | Q(name_en__icontains=q)
                | Q(course_code__icontains=q) | Q(teacher__icontains=q))
        .order_by('course_code', 'class_no', 'id')[:limit]
    )


# ---------------------------------------------------------------------------
# matching imported entries to catalog rows (README §8.1)
# ---------------------------------------------------------------------------

_ALL_SPACES_RE = re.compile(r'\s+')
_BRACKET_MAP = str.maketrans({'（': '(', '）': ')', '【': '[', '】': ']'})


def normalise_course_code(value: Any) -> str:
    """A course code trimmed and, when numeric, zero-padded to 8 digits."""
    text = _text(value)
    if text.isdigit() and len(text) < COURSE_CODE_DIGITS:
        text = text.zfill(COURSE_CODE_DIGITS)
    return text


def normalise_class_no(value: Any) -> str:
    """A class number trimmed and, when numeric, zero-padded to 2 digits."""
    text = _text(value)
    if text.isdigit() and len(text) < CLASS_NO_DIGITS:
        text = text.zfill(CLASS_NO_DIGITS)
    return text


def normalise_name(value: Any) -> str:
    """
    A course name or teacher for comparison: whitespace removed,
    case-folded, full-width brackets unified with ASCII ones.
    """
    return _ALL_SPACES_RE.sub('', str(value or '')).casefold().translate(_BRACKET_MAP)


class CatalogIndex:
    """
    In-memory lookup over the catalog rows of one term, built with one
    query (``for_term``) so an import can match every block without
    further queries. ``match`` implements the three steps of README §8.1.
    """

    def __init__(self, rows: Iterable[CourseCatalogEntry]):
        self.by_code_class: dict[tuple[str, str], CourseCatalogEntry] = {}
        self.by_code: dict[str, list[CourseCatalogEntry]] = {}
        self.by_name: dict[str, list[CourseCatalogEntry]] = {}
        for row in rows:
            code = normalise_course_code(row.course_code)
            class_no = normalise_class_no(row.class_no)
            self.by_code_class.setdefault((code, class_no), row)
            self.by_code.setdefault(code, []).append(row)
            self.by_name.setdefault(normalise_name(row.name), []).append(row)

    @classmethod
    def for_term(cls, term: AcademicTerm) -> 'CatalogIndex':
        """The index of every catalog row of ``term`` (one query)."""
        return cls(CourseCatalogEntry.objects.filter(term=term).order_by('id'))

    def match(self, *, course_code: str = '', class_no: str = '',
              name: str = '', teacher: str = '') -> CourseCatalogEntry | None:
        """
        The catalog row a block belongs to, or ``None``:

        1. ``course_code`` and ``class_no`` given → the exact row;
        2. only ``course_code`` → the row of that code when the term has
           exactly one;
        3. otherwise the row whose name equals ``name`` (whitespace- and
           case-insensitive) — narrowed by ``teacher`` when the block has
           one and some row carries that teacher — when exactly one
           matches. Ambiguity gives ``None``.
        """
        code = normalise_course_code(course_code)
        class_no = normalise_class_no(class_no)
        if code and class_no:
            return self.by_code_class.get((code, class_no))
        if code:
            rows = self.by_code.get(code, [])
            return rows[0] if len(rows) == 1 else None
        key = normalise_name(name)
        if not key:
            return None
        rows = self.by_name.get(key, [])
        teacher_key = normalise_name(teacher)
        if teacher_key:
            narrowed = [row for row in rows
                        if normalise_name(row.teacher) == teacher_key]
            if narrowed:
                rows = narrowed
        return rows[0] if len(rows) == 1 else None


def match_catalog(term: AcademicTerm, *, course_code: str = '', class_no: str = '',
                  name: str = '', teacher: str = '') -> CourseCatalogEntry | None:
    """
    The catalog row of ``term`` that a lesson block refers to (see
    ``CatalogIndex.match``), or ``None``. One query per call; callers
    matching many blocks should build ``CatalogIndex.for_term`` once.
    """
    return CatalogIndex.for_term(term).match(
        course_code=course_code, class_no=class_no, name=name, teacher=teacher)
