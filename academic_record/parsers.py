"""
Parser of the portal ``retrScores.do`` payload — pure functions, stdlib only.
Contract: ``timetable/README.md`` §6.2.

Undergraduate payloads (``"xslb": "bks"``) list scores under ``cjxx`` in one
of two shapes:

- nested (the portal itself): ``{"cjxx": [{"xnd": "25-26", "xq": "1",
  "list": [row, ...]}, ...]}``;
- flattened (what pkuhelper-web-score and the Treehole produce from
  ``c.list``): ``{"cjxx": [row, ...]}`` where every row carries its own
  ``xnd``/``xq``.

A row is a dict with ``kcmc`` (课程名), ``kch`` (课程号), ``xf`` (学分),
``xqcj`` (学期成绩), ``jd`` (绩点) and whatever else the portal adds.

Graduate payloads (``"xslb": "yjs"``) list scores under ``scoreLists``:
rows with ``kcmc``, ``xf``, ``cj`` (成绩; ``xqcj`` is accepted too),
``kclb``/``kclbmc`` (课程类别) and ``hgbz`` (合格标志, kept in ``raw``).
Their term keys are not confirmed: ``xnd`` + ``xq`` are read, then
``xndxq``, and a row naming neither goes to the term ``unknown``. Rows may
also come nested under ``list`` like ``cjxx``; ``cjxx`` rows of a graduate
payload are parsed as well.

Missing keys, numbers given as strings and non-numeric scores (``P``,
``合格``, ``W``, empty) are all tolerated; keys without a column of their own
are kept in :attr:`GradeRow.raw`. Values are cut to the column lengths of
``GradeRecord`` so live and stored rows are identical. Nothing outside the
score rows is read: the personal block ``jbxx`` never is, and the
辅修/双学位 list ``fscjxx`` (its GPA is kept apart from the main degree's),
the exchange list ``zjlcjxx`` and the thesis block are ignored.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

__all__ = [
    'GradeRow',
    'TermScores',
    'UNKNOWN_TERM',
    'term_code_of',
    'is_graduate_payload',
    'has_score_list',
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

# Term code of a graduate row that names no term.
UNKNOWN_TERM = 'unknown'
# ``xslb`` of a graduate payload.
_GRADUATE = 'yjs'

# Portal keys of each attribute, in order of preference. Only the key that
# was actually used is removed from ``raw``.
_NAME_KEYS = ('kcmc',)
_CODE_KEYS = ('kch',)
_CLASS_KEYS = ('bjh', 'bh', 'skbjh')
# ``kclbmc`` is the category name (任选, 通选课); undergraduate ``kclb`` is its
# numeric code ("30") and only graduate rows carry a readable ``kclb``.
_TYPE_KEYS = ('kclbmc', 'kclb', 'kcxz')
_CREDIT_KEYS = ('xf',)
_SCORE_KEYS = ('xqcj',)
_GRADUATE_SCORE_KEYS = ('cj', 'xqcj')
_GPA_KEYS = ('jd',)
_YEAR_KEYS = ('xnd',)
_SEMESTER_KEYS = ('xq',)
_TERM_KEYS = ('xndxq',)

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


def _graduate_term(year: Any, semester: Any, combined: Any) -> str:
    # xnd + xq, else xndxq, else the unknown term.
    if _text(year) and _text(semester):
        return term_code_of(year, semester)
    if _text(combined):
        return _cut(combined, 'term_code')
    return UNKNOWN_TERM


def is_graduate_payload(raw: Any) -> bool:
    """Whether ``raw`` is a graduate score payload (``xslb`` is ``yjs``)."""
    return isinstance(raw, dict) and _text(raw.get('xslb')) == _GRADUATE


def has_score_list(raw: Any) -> bool:
    """
    Whether ``raw`` carries a score list at all: a ``cjxx`` list, or for a
    graduate payload a ``scoreLists`` list. An empty list counts.
    """
    if not isinstance(raw, dict):
        return False
    if isinstance(raw.get('cjxx'), list):
        return True
    return is_graduate_payload(raw) and isinstance(raw.get('scoreLists'), list)


def parse_row(row: Any, term_code: str | None = None) -> GradeRow | None:
    """
    One portal row → :class:`GradeRow`, or ``None`` when it is not a dict
    or names no course (neither ``kcmc`` nor ``kch``).

    ``term_code`` is the enclosing term of the nested shape; when omitted
    the row's own ``xnd``/``xq`` are used (flattened shape). Either way the
    row's ``xnd``/``xq`` never end up in ``raw``.
    """
    return _parse_row(row, term_code, graduate=False)


def _parse_row(row: Any, term_code: str | None, *, graduate: bool) -> GradeRow | None:
    # ``parse_row`` for either payload kind; a graduate row takes its score
    # from ``cj`` first and its term from xnd + xq, xndxq or ``unknown``.
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
    score_value = take(_GRADUATE_SCORE_KEYS if graduate else _SCORE_KEYS)
    gpa = _float(take(_GPA_KEYS))
    year = take(_YEAR_KEYS)
    semester = take(_SEMESTER_KEYS)
    combined = take(_TERM_KEYS) if graduate else None
    if term_code is None:
        if graduate:
            term_code = _graduate_term(year, semester, combined)
        else:
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
    lists them: the ``cjxx`` rows, then — for a graduate payload — the
    ``scoreLists`` rows. Terms without a single usable row are omitted; a
    payload without a score list gives ``[]``.
    """
    if not isinstance(raw, dict):
        return []
    terms: dict[str, TermScores] = {}

    def add(parsed: GradeRow | None) -> None:
        if parsed is None:
            return
        term = terms.get(parsed.term_code)
        if term is None:
            term = terms[parsed.term_code] = TermScores(parsed.term_code)
        term.rows.append(parsed)

    def add_blocks(blocks: Any, *, graduate: bool) -> None:
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if not isinstance(block, dict):
                continue
            rows = block.get('list')
            if not isinstance(rows, list):
                # Flattened shape: the block is a row carrying its own term.
                add(_parse_row(block, None, graduate=graduate))
                continue
            if graduate:
                code = _graduate_term(block.get('xnd'), block.get('xq'),
                                      block.get('xndxq'))
                if code == UNKNOWN_TERM:
                    # A block without a term: each row names its own.
                    code = None
            else:
                code = term_code_of(block.get('xnd'), block.get('xq'))
            for row in rows:
                add(_parse_row(row, code, graduate=graduate))

    add_blocks(raw.get('cjxx'), graduate=False)
    if is_graduate_payload(raw):
        add_blocks(raw.get('scoreLists'), graduate=True)
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
