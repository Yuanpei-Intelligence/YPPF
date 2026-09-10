"""
Exam schedule helpers (``timetable/README.md`` §8.4): the pure parser of
the 教务部 exam-time cell and the matching of ``CourseExam`` rows to a
person's course entries, shared by ``timetable.sources.exam.ExamSource``
(one occurrence per exam) and the ``Entry.exam`` payload (first matching
exam by time).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from timetable.catalog import normalise_class_no, normalise_course_code, normalise_name
from timetable.models import AcademicTerm, CourseExam, TimetableEntry

__all__ = [
    'DEFAULT_EXAM_HOURS',
    'parse_exam_time',
    'ExamIndex',
    'entry_exam_keys',
    'match_exams',
    'exams_for_entries',
]

# An exam without an end time lasts this long (README §8.4).
DEFAULT_EXAM_HOURS = 2
# Month-day cells resolve their year inside this window around week 1.
_BEFORE_WEEK1 = timedelta(days=42)
_AFTER_WEEK1 = timedelta(days=364)

_SPACES_RE = re.compile(r'[\s　]+')
# 2027-01-11, 2027/1/11, 2027.1.11 (full-width variants accepted).
_YMD_RE = re.compile(r'(\d{4})\s*[-/.／．]\s*(\d{1,2})\s*[-/.／．]\s*(\d{1,2})')
_CN_YMD_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?')
_CN_MD_RE = re.compile(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?')
_WEEK_RE = re.compile(r'第?\s*(\d{1,2})\s*周')
_WEEKDAY_RE = re.compile(r'(?:周|星期|礼拜)\s*([一二三四五六日天1-7])')
_WEEKDAY_TOKENS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 7, '天': 7,
    '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
}
# 08:30, 8：30, 8点30(分), 8时30分, optional seconds.
_TIME_RE = re.compile(
    r'(?<!\d)(\d{1,2})\s*[:：点时]\s*(\d{1,2})\s*分?(?:\s*[:：]\s*\d{1,2})?')
_PM_MARKERS = ('下午', '晚上', '晚间', '傍晚')


def _text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime):
        if value.hour or value.minute:
            return value.strftime('%Y-%m-%d %H:%M')
        return value.strftime('%Y-%m-%d')
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, 'strftime') and hasattr(value, 'hour'):
        # A datetime.time cell of a workbook.
        return value.strftime('%H:%M')
    return _SPACES_RE.sub(' ', str(value)).strip()


def _resolve_year(term: AcademicTerm, month: int, day: int) -> date | None:
    # The year of a month-day cell: the one placing the date inside the
    # term's year (fall terms span two calendar years).
    first = term.week1_monday.year
    low, high = term.week1_monday - _BEFORE_WEEK1, term.week1_monday + _AFTER_WEEK1
    candidates: list[date] = []
    for year in (first, first + 1, first - 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    for candidate in candidates:
        if low <= candidate <= high:
            return candidate
    return candidates[0] if candidates else None


def _find_date(text: str, term: AcademicTerm) -> tuple[date | None, str]:
    # (date, text with the date part removed) — None when no date is found.
    for pattern in (_YMD_RE, _CN_YMD_RE):
        match = pattern.search(text)
        if match is None:
            continue
        year, month, day = (int(group) for group in match.groups())
        try:
            found = date(year, month, day)
        except ValueError:
            return None, text
        return found, text[:match.start()] + ' ' + text[match.end():]
    match = _CN_MD_RE.search(text)
    if match is not None:
        month, day = int(match.group(1)), int(match.group(2))
        found = _resolve_year(term, month, day)
        if found is None:
            return None, text
        return found, text[:match.start()] + ' ' + text[match.end():]
    week_match = _WEEK_RE.search(text)
    if week_match is None:
        return None, text
    remainder = text[:week_match.start()] + ' ' + text[week_match.end():]
    weekday_match = _WEEKDAY_RE.search(remainder)
    if weekday_match is None:
        return None, text
    week = int(week_match.group(1))
    weekday = _WEEKDAY_TOKENS[weekday_match.group(1)]
    if week < 1:
        return None, text
    remainder = remainder[:weekday_match.start()] + ' ' + remainder[weekday_match.end():]
    return term.date_of(week, weekday), remainder


def _find_times(text: str) -> list[tuple[int, int]]:
    # Every ``(hour, minute)`` in ``text``; a 下午/晚上 marker before a
    # time turns an hour below 12 into an afternoon hour.
    times: list[tuple[int, int]] = []
    for match in _TIME_RE.finditer(text):
        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        before = text[:match.start()]
        marker = max((before.rfind(marker) for marker in _PM_MARKERS), default=-1)
        morning = before.rfind('上午')
        if marker > morning and hour < 12:
            hour += 12
        times.append((hour, minute))
    return times


def parse_exam_time(text: Any, term: AcademicTerm, *, start_text: Any = '',
                    end_text: Any = '') -> tuple[datetime, datetime] | None:
    """
    ``(start, end)`` of an exam-time cell, or ``None`` when it cannot be
    read. ``text`` may be ``2027-01-11 08:30-10:30``, ``2027/1/11
    8:30～10:30``, ``2027年1月11日 08:30-10:30``, ``1月11日（周一）8:30-10:30``
    (year from the term's span), ``第19周 周一 08:30-10:30`` (resolved with
    ``term.date_of``) or a date alone with the times in ``start_text`` /
    ``end_text`` (separate 开始时间/结束时间 columns; a datetime in
    ``start_text`` also supplies the date). A missing end is ``start`` plus
    ``DEFAULT_EXAM_HOURS``; so is an end that does not follow the start.
    Workbook cells that are already ``datetime``/``time`` values are
    accepted.
    """
    parts = [_text(text)]
    if _text(start_text):
        parts.append(_text(start_text))
        if _text(end_text):
            parts.append('~' + _text(end_text))
    combined = ' '.join(parts)
    exam_date, remainder = _find_date(combined, term)
    if exam_date is None:
        return None
    times = _find_times(remainder)
    if not times:
        return None
    start = datetime.combine(exam_date, datetime.min.time()).replace(
        hour=times[0][0], minute=times[0][1])
    end = None
    if len(times) > 1:
        end = start.replace(hour=times[1][0], minute=times[1][1])
    if end is None or end <= start:
        end = start + timedelta(hours=DEFAULT_EXAM_HOURS)
    return start, end


# ---------------------------------------------------------------------------
# matching exams to entries
# ---------------------------------------------------------------------------

def entry_exam_keys(entry: TimetableEntry) -> tuple[str, str, list[str]]:
    """
    ``(course_code, class_no, names)`` an entry is matched by: the catalog
    row's code/class when linked, else the entry's own; ``names`` are the
    normalised entry name and, when linked, the catalog name.
    """
    catalog = entry.catalog_entry if entry.catalog_entry_id else None
    if catalog is not None:
        code = normalise_course_code(catalog.course_code)
        class_no = normalise_class_no(catalog.class_no)
    else:
        code = normalise_course_code(entry.course_code)
        class_no = normalise_class_no(entry.class_no)
    names: list[str] = []
    for value in (entry.name, catalog.name if catalog is not None else ''):
        key = normalise_name(value)
        if key and key not in names:
            names.append(key)
    return code, class_no, names


class ExamIndex:
    """Lookup over the ``CourseExam`` rows of one term (README §8.4 rules)."""

    def __init__(self, exams: Iterable[CourseExam]):
        self.by_code_class: dict[tuple[str, str], list[CourseExam]] = {}
        self.by_code: dict[str, list[CourseExam]] = {}
        self.by_name: dict[str, list[CourseExam]] = {}
        for exam in sorted(exams, key=lambda item: (item.start, item.pk or 0)):
            code = normalise_course_code(exam.course_code)
            class_no = normalise_class_no(exam.class_no)
            self.by_code_class.setdefault((code, class_no), []).append(exam)
            self.by_code.setdefault(code, []).append(exam)
            self.by_name.setdefault(normalise_name(exam.name), []).append(exam)

    @classmethod
    def for_term(cls, term: AcademicTerm) -> 'ExamIndex':
        """The index of every exam of ``term`` (one query)."""
        return cls(CourseExam.objects.filter(term=term).order_by('start', 'id'))

    def match_entry(self, entry: TimetableEntry) -> list[CourseExam]:
        """
        The exams of one entry, by time: the rows of ``(course_code,
        class_no)``; else, with a code only, the rows of that code when
        they all belong to one class; else the rows of the exact name when
        they all belong to one class. Ambiguity gives nothing.
        """
        code, class_no, names = entry_exam_keys(entry)
        if code and class_no:
            return list(self.by_code_class.get((code, class_no), []))
        if code:
            return _single_class(self.by_code.get(code, []))
        for name in names:
            found = _single_class(self.by_name.get(name, []))
            if found:
                return found
        return []


def _single_class(exams: list[CourseExam]) -> list[CourseExam]:
    # The rows when they all belong to one (course_code, class_no).
    keys = {(normalise_course_code(exam.course_code), normalise_class_no(exam.class_no))
            for exam in exams}
    return list(exams) if len(keys) == 1 else []


def match_exams(entries: Iterable[TimetableEntry],
                exams: Iterable[CourseExam]) -> list[tuple[CourseExam, TimetableEntry]]:
    """
    ``(exam, entry)`` pairs for the exams of ``exams`` matched by
    ``entries`` (see ``ExamIndex.match_entry``), each exam at most once —
    the first entry in the given order keeps it — ordered by exam time.
    """
    index = ExamIndex(exams)
    taken: dict[int, tuple[CourseExam, TimetableEntry]] = {}
    for entry in entries:
        for exam in index.match_entry(entry):
            taken.setdefault(exam.pk, (exam, entry))
    return sorted(taken.values(), key=lambda pair: (pair[0].start, pair[0].pk or 0))


def exams_for_entries(term: AcademicTerm,
                      entries: Iterable[TimetableEntry]) -> dict[int, list[CourseExam]]:
    """``{entry id: matching exams by time}`` for entries of ``term`` (one query)."""
    entries = list(entries)
    if not entries:
        return {}
    index = ExamIndex.for_term(term)
    return {entry.pk: index.match_entry(entry) for entry in entries}
