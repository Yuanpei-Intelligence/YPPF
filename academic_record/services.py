"""
Domain operations of the grade records (``timetable/README.md`` §6.2):
fetch the live score list through the ``pku_account`` binding, store it for
students who consented, read / wipe what is stored, build the API payload.

Nothing here touches credentials; the portal session comes from
``pku_account.services.get_client``. Score payloads are personal data and
are never logged.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max

from app.models import NaturalPerson
from generic.models import User
from pku_account.config import CONFIG as PKU_CONFIG
from pku_account.extern.portal import PortalSessionExpired
from pku_account.models import PkuAccount
from pku_account.services import (
    NotBound,
    PortalDisabled,
    get_binding,
    get_client,
    invalidate_session,
    mark_session_ok,
)
from academic_record.models import GradeRecord
from academic_record.parsers import (
    GradeRow,
    TermScores,
    has_score_list,
    parse_scores,
    summary,
)

__all__ = [
    'ScoresUnavailable',
    'fetch_scores',
    'store_scores',
    'stored_terms',
    'last_fetched_at',
    'delete_stored',
    'grades_payload',
]

logger = logging.getLogger(__name__)

# Columns of ``GradeRecord`` that come from a ``GradeRow``, and the part of
# them that (with ``person``) forms the unique key.
_ROW_FIELDS = (
    'term_code', 'course_code', 'class_no', 'name', 'course_type',
    'credits', 'score', 'score_numeric', 'gpa', 'raw',
)
_KEY_FIELDS = ('term_code', 'course_code', 'name')
_NO_SCORES_MESSAGE = '门户未返回成绩数据，请稍后再试'


class ScoresUnavailable(Exception):
    """The portal answered with JSON, but not with a score list."""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime('%Y-%m-%dT%H:%M:%S')


def _check_payload(raw: Any) -> None:
    # A usable answer has a score list (``cjxx``, or a graduate's
    # ``scoreLists``) and no explicit ``success: false``.
    if has_score_list(raw) and raw.get('success') is not False:
        return
    message = ''
    if isinstance(raw, dict):
        for key in ('remark', 'msg', 'message'):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                message = value.strip()
                break
    raise ScoresUnavailable(message or _NO_SCORES_MESSAGE)


def fetch_scores(user: User) -> tuple[list[TermScores], PkuAccount]:
    """
    Fetch the live score list of the user's PKU account.

    Marks the stored session as working (and the binding as synced) on
    success. Nothing is stored here; see :func:`store_scores`.

    Raises:
        PortalDisabled: ``pku_portal.enabled`` is false.
        NotBound: the user has no binding.
        SessionUnavailable: no usable stored session; log in again.
        PortalSessionExpired: the portal rejected the session, which has
            been marked invalid; log in again.
        PortalUnreachable: pku.edu.cn could not be reached.
        ScoresUnavailable: the portal answered without a score list.
    """
    if not PKU_CONFIG.enabled:
        raise PortalDisabled('北大门户功能未启用')
    account = get_binding(user)
    if account is None:
        raise NotBound('尚未绑定北大账号')
    client = get_client(user)
    # Network I/O: no transaction is open here.
    try:
        raw = client.get_scores()
    except PortalSessionExpired:
        invalidate_session(account, 'expired')
        raise
    _check_payload(raw)
    terms = parse_scores(raw)
    mark_session_ok(account)
    return terms, account


def _record_fields(row: GradeRow) -> dict[str, Any]:
    return {
        'term_code': row.term_code,
        'course_code': row.course_code,
        'class_no': row.class_no,
        'name': row.name,
        'course_type': row.course_type,
        'credits': row.credits,
        'score': row.score,
        'score_numeric': row.score_numeric,
        'gpa': row.gpa,
        'raw': row.raw,
    }


def _create_rows(person: NaturalPerson, records: list[GradeRecord]) -> set[int]:
    """
    Insert ``records`` (new rows by exact key comparison). Returns the
    primary keys of *stored* rows that the database matched to one of them
    instead of inserting it.

    The unique key is compared with the column collation, which on MySQL
    may equate names that differ only in case or character width; Python
    compared them exactly. When the bulk insert hits the unique key, the
    rows are stored one by one and the database decides which stored row
    each of them is.
    """
    if not records:
        return set()
    try:
        with transaction.atomic():
            GradeRecord.objects.bulk_create(records)
    except IntegrityError:
        pass
    else:
        return set()
    matched: set[int] = set()
    for record in records:
        defaults = {
            name: getattr(record, name)
            for name in _ROW_FIELDS if name not in _KEY_FIELDS
        }
        defaults['fetched_at'] = record.fetched_at
        stored, created = GradeRecord.objects.update_or_create(
            person=person, term_code=record.term_code,
            course_code=record.course_code, name=record.name,
            defaults=defaults,
        )
        if not created:
            matched.add(stored.pk)
    return matched


def _store_term(
    person: NaturalPerson, term: TermScores, fetched_at: datetime,
) -> int:
    # Upsert one term; returns the number of rows written.
    existing = {
        (record.course_code, record.name): record
        for record in GradeRecord.objects.filter(
            person=person, term_code=term.term_code,
        )
    }
    seen: set[tuple[str, str]] = set()
    to_create: list[GradeRecord] = []
    to_update: list[GradeRecord] = []
    for row in term.rows:
        key = (row.course_code, row.name)
        if key in seen:
            # The unique key admits one row per course; keep the first
            # occurrence of a duplicated portal row.
            continue
        seen.add(key)
        record = existing.get(key)
        if record is None:
            to_create.append(GradeRecord(
                person=person, fetched_at=fetched_at, **_record_fields(row),
            ))
            continue
        for name, value in _record_fields(row).items():
            setattr(record, name, value)
        record.fetched_at = fetched_at
        to_update.append(record)
    GradeRecord.objects.bulk_update(to_update, [*_ROW_FIELDS, 'fetched_at'])
    kept = {record.pk for record in to_update}
    kept |= _create_rows(person, to_create)
    vanished = [
        record.pk for record in existing.values() if record.pk not in kept
    ]
    if vanished:
        GradeRecord.objects.filter(pk__in=vanished).delete()
    return len(to_create) + len(to_update)


def store_scores(
    person: NaturalPerson, terms: list[TermScores], fetched_at: datetime,
) -> int:
    """
    Upsert the rows of every term in ``terms`` for ``person``: rows are
    matched on ``(term_code, course_code, name)``, existing rows are
    refreshed (``fetched_at`` included), and stored rows of those terms
    that the portal no longer lists are deleted. Terms absent from
    ``terms`` are left untouched. Only call this when the binding carries
    ``consent_grades``.

    Returns the number of rows written for the given terms.
    """
    written = 0
    with transaction.atomic():
        # One sync of a person at a time, so two concurrent syncs cannot
        # both insert the same unique key.
        NaturalPerson.objects.select_for_update().get(pk=person.pk)
        for term in terms:
            written += _store_term(person, term, fetched_at)
    return written


def _row_of(record: GradeRecord) -> GradeRow:
    return GradeRow(
        term_code=record.term_code,
        name=record.name,
        course_code=record.course_code,
        class_no=record.class_no,
        course_type=record.course_type,
        credits=record.credits,
        score=record.score,
        score_numeric=record.score_numeric,
        gpa=record.gpa,
        raw=record.raw if isinstance(record.raw, dict) else {},
    )


def stored_terms(person: NaturalPerson) -> list[TermScores]:
    """The person's stored rows grouped by term, newest term first."""
    terms: dict[str, TermScores] = {}
    records = GradeRecord.objects.filter(person=person).order_by(
        '-term_code', 'id')
    for record in records:
        term = terms.get(record.term_code)
        if term is None:
            term = terms[record.term_code] = TermScores(record.term_code)
        term.rows.append(_row_of(record))
    return list(terms.values())


def last_fetched_at(person: NaturalPerson) -> datetime | None:
    """When the person's stored rows were last fetched; ``None`` if none."""
    return GradeRecord.objects.filter(person=person).aggregate(
        latest=Max('fetched_at'))['latest']


def delete_stored(person: NaturalPerson) -> int:
    """Delete every stored row of the person; returns the number deleted."""
    deleted, _ = GradeRecord.objects.filter(person=person).delete()
    if deleted:
        logger.info('deleted %s stored grade rows of person #%s',
                    deleted, person.pk)
    return deleted


def grades_payload(
    terms: list[TermScores], *, stored: bool, fetched_at: datetime | None,
) -> dict[str, Any]:
    """
    The ``GradesOut`` shape of ``timetable/README.md`` §6.2: terms newest
    first, rows in their given order, overall and per-term summaries.
    """
    ordered = sorted(terms, key=lambda term: term.term_code, reverse=True)
    all_rows = [row for term in ordered for row in term.rows]
    return {
        'stored': stored,
        'fetched_at': _iso(fetched_at),
        'summary': summary(all_rows),
        'terms': [
            {
                'term_code': term.term_code,
                'summary': summary(term.rows),
                'rows': [row.as_dict() for row in term.rows],
            }
            for term in ordered
        ],
    }
