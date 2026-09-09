"""
Parser of the portal ``retrScores.do`` payload — pure functions, stdlib only.
Contract: ``timetable/README.md`` §6.2.

Two payload shapes are accepted:

- nested (the portal itself): ``{"cjxx": [{"xnd": "25-26", "xq": "1",
  "list": [row, ...]}, ...]}``;
- flattened (what pkuhelper-web-score produces from ``c.list``):
  ``{"cjxx": [row, ...]}`` where every row carries its own ``xnd``/``xq``.

A row is a dict with ``kcmc`` (课程名), ``kch`` (课程号), ``xf`` (学分),
``xqcj`` (学期成绩), ``jd`` (绩点) and whatever else the portal adds. Missing
keys, numbers given as strings and non-numeric scores (``P``, ``合格``,
``W``, empty) are all tolerated; keys without a column of their own are
kept in :attr:`GradeRow.raw`. Values are cut to the column lengths of
``GradeRecord`` so live and stored rows are identical.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

__all__ = [
    'GradeRow',
    'TermScores',
    'term_code_of',
    'parse_row',
    'parse_scores',
    'summary',
]

# Column lengths of ``academic_record.models.GradeRecord``.
MAX_LENGTHS = {
    'term_code': 16,
    'course_code': 32,
    'class_no': 8,
    'name': 80,
    'course_type': 32,
    'score': 16,
}

# Portal keys of each attribute, in order of preference. Only the key that
# was actually used is removed from ``raw``.
_NAME_KEYS = ('kcmc',)
_CODE_KEYS = ('kch',)
_CLASS_KEYS = ('bjh', 'bh', 'skbjh')
_TYPE_KEYS = ('kclb', 'kclbmc', 'kcxz')
_CREDIT_KEYS = ('xf',)
_SCORE_KEYS = ('xqcj',)
_GPA_KEYS = ('jd',)
_YEAR_KEYS = ('xnd',)
_SEMESTER_KEYS = ('xq',)

# ``DecimalField(max_digits=4, decimal_places=1)``: |credits| < 1000.
_CREDIT_LIMIT = Decimal(1000)
_CREDIT_STEP = Decimal('0.1')


@dataclass
class GradeRow:
    """One course grade; ``raw`` is the rest of the portal row."""

    term_code: str
    name: str
    course_code: str = ''
    class_no: str = ''
    course_type: str = ''
    credits: Decimal | None = None
    score: str = ''
    score_numeric: float | None = None
    gpa: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        """The part of ``GradeRecord``'s unique key that comes from the row."""
        return (self.term_code, self.course_code, self.name)

    def as_dict(self) -> dict[str, Any]:
        """The API ``GradeRow`` shape (``raw`` is deliberately left out)."""
        return {
            'term_code': self.term_code,
            'course_code': self.course_code,
            'class_no': self.class_no,
            'name': self.name,
            'course_type': self.course_type,
            'credits': float(self.credits) if self.credits is not None else None,
            'score': self.score,
            'score_numeric': self.score_numeric,
            'gpa': self.gpa,
        }


@dataclass
class TermScores:
    """The rows of one term, in portal order."""

    term_code: str
    rows: list[GradeRow] = field(default_factory=list)


def _text(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _cut(value: Any, name: str) -> str:
    return _text(value)[:MAX_LENGTHS[name]]


def _float(value: Any) -> float | None:
    # A finite number or None; booleans and text such as 'P' give None.
    if isinstance(value, bool):
        return None
    text = _text(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _credits(value: Any) -> Decimal | None:
    # Credits as stored by ``GradeRecord.credits`` (one decimal place).
    if isinstance(value, bool):
        return None
    text = _text(value)
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) >= _CREDIT_LIMIT:
        return None
    return number.quantize(_CREDIT_STEP, rounding=ROUND_HALF_UP)


def term_code_of(year: Any, semester: Any) -> str:
    """``'25-26'`` + ``'1'`` → ``'25-26-1'``; a missing part is left out."""
    parts = [part for part in (_text(year), _text(semester)) if part]
    return '-'.join(parts)[:MAX_LENGTHS['term_code']]


def parse_row(row: Any, term_code: str | None = None) -> GradeRow | None:
    """
    One portal row → :class:`GradeRow`, or ``None`` when it is not a dict
    or names no course (neither ``kcmc`` nor ``kch``).

    ``term_code`` is the enclosing term of the nested shape; when omitted
    the row's own ``xnd``/``xq`` are used (flattened shape). Either way the
    row's ``xnd``/``xq`` never end up in ``raw``.
    """
    if not isinstance(row, dict):
        return None
    consumed: set[str] = set()

    def take(keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in row:
                consumed.add(key)
                return row[key]
        return None

    name = _cut(take(_NAME_KEYS), 'name')
    course_code = _cut(take(_CODE_KEYS), 'course_code')
    class_no = _cut(take(_CLASS_KEYS), 'class_no')
    course_type = _cut(take(_TYPE_KEYS), 'course_type')
    credits = _credits(take(_CREDIT_KEYS))
    score_value = take(_SCORE_KEYS)
    gpa = _float(take(_GPA_KEYS))
    year = take(_YEAR_KEYS)
    semester = take(_SEMESTER_KEYS)
    if term_code is None:
        term_code = term_code_of(year, semester)
    if not name and not course_code:
        return None
    return GradeRow(
        term_code=term_code,
        name=name,
        course_code=course_code,
        class_no=class_no,
        course_type=course_type,
        credits=credits,
        score=_cut(score_value, 'score'),
        score_numeric=_float(score_value),
        gpa=gpa,
        raw={key: value for key, value in row.items() if key not in consumed},
    )


def parse_scores(raw: Any) -> list[TermScores]:
    """
    Every term of a ``retrScores.do`` payload, in the order the portal
    lists them. Terms without a single usable row are omitted; a payload
    without a ``cjxx`` list gives ``[]``.
    """
    if not isinstance(raw, dict):
        return []
    blocks = raw.get('cjxx')
    if not isinstance(blocks, list):
        return []
    terms: dict[str, TermScores] = {}

    def add(parsed: GradeRow | None) -> None:
        if parsed is None:
            return
        term = terms.get(parsed.term_code)
        if term is None:
            term = terms[parsed.term_code] = TermScores(parsed.term_code)
        term.rows.append(parsed)

    for block in blocks:
        if not isinstance(block, dict):
            continue
        rows = block.get('list')
        if isinstance(rows, list):
            code = term_code_of(block.get('xnd'), block.get('xq'))
            for row in rows:
                add(parse_row(row, code))
        else:
            # Flattened shape: the block is a row carrying its own term.
            add(parse_row(block))
    return list(terms.values())


def summary(rows: Iterable[GradeRow]) -> dict[str, float | None]:
    """
    ``{credits, gpa}`` of some rows: ``credits`` is the sum over rows that
    have credits; ``gpa`` is Σ(gpa·credits) / Σcredits over rows that have
    both, rounded to three decimals, ``None`` when no row qualifies.
    """
    total_credits = Decimal(0)
    weighted_points = 0.0
    weighted_credits = Decimal(0)
    for row in rows:
        if row.credits is None:
            continue
        total_credits += row.credits
        if row.gpa is None:
            continue
        weighted_points += row.gpa * float(row.credits)
        weighted_credits += row.credits
    gpa = None
    if weighted_credits > 0:
        gpa = round(weighted_points / float(weighted_credits), 3)
    return {'credits': float(total_credits), 'gpa': gpa}
