'''
Anonymized development database sample export.

Sample about ``ratio`` of ``generic.User`` rows (fixed seed), cascade related
records, rewrite identity fields to category+index labels, and write an
INSERT-only SQL dump suitable for import after ``migrate``.
'''

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from django.db import connection

from generic.models import User

__all__ = [
    'SAMPLE_PASSWORD_HASH',
    'SAMPLE_PASSWORD_PLAINTEXT',
    'export_sample_database',
]

# Django pbkdf2 hash of the plaintext password "test" (development samples only).
SAMPLE_PASSWORD_HASH = (
    'pbkdf2_sha256$1000000$dGQo0oBkjKFUB7JeCtrtky$'
    'cj/291X3R/f1+HqppYf/fF8L6EvdsLfHZmY6caZU9Ag='
)
SAMPLE_PASSWORD_PLAINTEXT = 'test'

REDACTED = '[redacted]'
USAGE_SAMPLE = '样例'
BATCH_SIZE = 100

# Tables exported fully (configuration / reference data).
FULL_TABLES: list[str] = [
    'semester_semestertype',
    'semester_semester',
    'app_organizationtag',
    'app_organizationtype',
    'Appointment_room',
    'dormitory_dormitory',
    # feedback_feedbacktype: written separately to null dangling org defaults.
    'app_academictag',
    'achievement_achievementtype',
    'achievement_achievement',
    'app_help',
]


@dataclass
class UserAlias:
    '''Anonymized fields for one retained User row.'''

    old_id: int
    old_username: str
    new_username: str
    new_name: str
    pinyin: str
    acronym: str
    utype: str
    email: str


@dataclass
class SampleContext:
    '''Mutable export state: selected keys and username remapping.'''

    ratio: float
    seed: int
    user_by_id: dict[int, UserAlias] = field(default_factory=dict)
    username_map: dict[str, str] = field(default_factory=dict)
    person_ids: set[int] = field(default_factory=set)
    org_ids: set[int] = field(default_factory=set)
    participant_usernames: set[str] = field(default_factory=set)
    activity_ids: set[int] = field(default_factory=set)
    commentbase_ids: set[int] = field(default_factory=set)
    course_ids: set[int] = field(default_factory=set)
    coursetime_ids: set[int] = field(default_factory=set)
    pool_ids: set[int] = field(default_factory=set)
    poolitem_ids: set[int] = field(default_factory=set)
    appoint_ids: set[int] = field(default_factory=set)
    survey_ids: set[int] = field(default_factory=set)
    question_ids: set[int] = field(default_factory=set)
    answersheet_ids: set[int] = field(default_factory=set)
    reader_ids: set[int] = field(default_factory=set)
    book_ids: set[int] = field(default_factory=set)
    freshman_ids: set[int] = field(default_factory=set)
    feedback_ids: set[int] = field(default_factory=set)
    position_ids: set[int] = field(default_factory=set)

    @property
    def user_ids(self) -> set[int]:
        return set(self.user_by_id)

    @property
    def new_usernames(self) -> set[str]:
        return set(self.username_map.values())


def export_sample_database(
    outfile: Path,
    *,
    ratio: float = 0.1,
    seed: int = 42,
) -> dict[str, Any]:
    '''
    Export an anonymized sample dump to ``outfile``.

    :return: Summary dict with ratio, seed, user count, and output path.
    '''
    if not 0 < ratio <= 1:
        raise ValueError('ratio must be in (0, 1]')

    ctx = SampleContext(ratio=ratio, seed=seed)
    _sample_users(ctx)
    _expand_and_collect(ctx)

    outfile.parent.mkdir(parents=True, exist_ok=True)
    with outfile.open('w', encoding='utf-8', newline='\n') as fh:
        fh.write('-- YPPF anonymized sample dump for development\n')
        fh.write(
            f'-- ratio={ratio} seed={seed} users={len(ctx.user_by_id)}\n'
        )
        fh.write('-- Import after: CREATE DATABASE + migrate\n')
        fh.write('SET NAMES utf8mb4;\n')
        fh.write('SET FOREIGN_KEY_CHECKS=0;\n')
        fh.write('SET UNIQUE_CHECKS=0;\n')
        fh.write('\n')
        _write_all_tables(fh, ctx)
        fh.write('\n')
        fh.write('SET UNIQUE_CHECKS=1;\n')
        fh.write('SET FOREIGN_KEY_CHECKS=1;\n')

    return {
        'ratio': ratio,
        'seed': seed,
        'users': len(ctx.user_by_id),
        'path': str(outfile),
    }


def _sample_users(ctx: SampleContext) -> None:
    rows = list(
        User.objects.order_by('pk').values_list('id', 'username', 'utype')
    )
    if not rows:
        raise RuntimeError('No users in database; nothing to sample')

    rng = random.Random(ctx.seed)
    count = max(1, int(len(rows) * ctx.ratio))
    count = min(count, len(rows))
    chosen = rng.sample(rows, count)
    _assign_aliases(ctx, chosen)


def _assign_aliases(
    ctx: SampleContext,
    users: Sequence[tuple[int, str, str]],
) -> None:
    '''Build anonymized usernames/names for the given users.'''
    counters = {
        User.Type.STUDENT: 0,
        User.Type.ORG: 0,
        User.Type.PERSON: 0,
        User.Type.TEACHER: 0,
        User.Type.UNAUTHORIZED: 0,
        User.Type.SPECIAL: 0,
        '': 0,
    }

    # Stable order by old id so remapping is deterministic given the set.
    for old_id, old_username, utype in sorted(users, key=lambda x: x[0]):
        utype = utype or ''
        if utype == User.Type.STUDENT:
            counters[User.Type.STUDENT] += 1
            n = counters[User.Type.STUDENT]
            new_username = f'S{n:06d}'
            new_name = f'学生{n}'
            pinyin = f'xuesheng{n}'
            acronym = f'xs{str(n)[0]}'
        elif utype == User.Type.ORG:
            counters[User.Type.ORG] += 1
            n = counters[User.Type.ORG]
            new_username = f'O{n:06d}'
            new_name = f'组织{n}'
            pinyin = f'zuzhi{n}'
            acronym = f'zz{str(n)[0]}'
        elif utype in (User.Type.PERSON, User.Type.TEACHER):
            # Match existing sample: Person/Teacher share P/用户 series.
            counters[User.Type.PERSON] += 1
            n = counters[User.Type.PERSON]
            new_username = f'P{n:06d}'
            new_name = f'用户{n}'
            pinyin = f'yonghu{n}'
            acronym = f'yh{str(n)[0]}'
        else:
            counters[User.Type.SPECIAL] += 1
            n = counters[User.Type.SPECIAL]
            new_username = f'X{n:06d}'
            new_name = f'账号{n}'
            pinyin = f'zhanghao{n}'
            acronym = f'zh{str(n)[0]}'

        alias = UserAlias(
            old_id=old_id,
            old_username=old_username,
            new_username=new_username,
            new_name=new_name,
            pinyin=pinyin,
            acronym=acronym[:32],
            utype=utype,
            email=f'{new_username.lower()}@example.com',
        )
        ctx.user_by_id[old_id] = alias
        ctx.username_map[old_username] = new_username


def _ensure_user_ids(ctx: SampleContext, user_ids: Iterable[int]) -> None:
    '''Force-include users referenced by retained rows (FK closure).'''
    missing = [
        uid for uid in set(user_ids)
        if uid is not None and int(uid) not in ctx.user_by_id
    ]
    if not missing:
        return
    rows = list(
        User.objects.filter(pk__in=missing).values_list(
            'id', 'username', 'utype'
        )
    )
    if not rows:
        return
    existing = [
        (alias.old_id, alias.old_username, alias.utype)
        for alias in ctx.user_by_id.values()
    ]
    ctx.user_by_id.clear()
    ctx.username_map.clear()
    _assign_aliases(ctx, existing + rows)


def _expand_and_collect(ctx: SampleContext) -> None:
    '''
    Collect related primary keys for the sampled users.

    Referenced-but-missing users (e.g. examine teachers) are added as leaf
    identities only: their User/NaturalPerson rows are exported, but they do
    not trigger another round of appointment/position/notification expansion.
    '''
    _collect_profiles(ctx)
    _collect_positions_and_courses(ctx)
    _collect_activities(ctx)
    _collect_appointments(ctx)
    # Leaf users required by activity teachers / appoint majors already added.
    _collect_profiles(ctx)
    _collect_feedback_comments_notifications(ctx)
    _collect_pools_academic_achievements(ctx)
    _collect_questionnaire(ctx)
    _collect_library_dorm_logs(ctx)
    _collect_freshmen(ctx)
    # Ensure orgtype incharge persons exist as leaf rows (or null at write).
    _collect_orgtype_incharge_leaf(ctx)
    _collect_profiles(ctx)


def _fetch_ids(sql: str, params: Sequence[Any] | None = None) -> set[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return {row[0] for row in cursor.fetchall() if row[0] is not None}


def _in_clause(ids: Sequence[Any]) -> tuple[str, list[Any]]:
    if not ids:
        return 'NULL', []
    placeholders = ','.join(['%s'] * len(ids))
    return placeholders, list(ids)


def _collect_profiles(ctx: SampleContext) -> None:
    uids = list(ctx.user_ids)
    if not uids:
        return
    ph, params = _in_clause(uids)
    ctx.person_ids |= _fetch_ids(
        f'SELECT id FROM app_naturalperson WHERE person_id_id IN ({ph})',
        params,
    )
    ctx.org_ids |= _fetch_ids(
        f'SELECT id FROM app_organization WHERE organization_id_id IN ({ph})',
        params,
    )
    # Participants keyed by username.
    unames = list(ctx.username_map)
    if unames:
        ph, params = _in_clause(unames)
        ctx.participant_usernames |= _fetch_ids(
            f'SELECT Sid_id FROM Appointment_participant WHERE Sid_id IN ({ph})',
            params,
        )


def _collect_orgtype_incharge_leaf(ctx: SampleContext) -> None:
    '''Include incharge persons only when their org type is used by sample orgs.'''
    if not ctx.org_ids:
        return
    ph, params = _in_clause(list(ctx.org_ids))
    otypes = _fetch_ids(
        f'SELECT DISTINCT otype_id FROM app_organization WHERE id IN ({ph})',
        params,
    )
    if not otypes:
        return
    ph2, params2 = _in_clause(list(otypes))
    incharge_users = _fetch_ids(
        'SELECT np.person_id_id FROM app_organizationtype ot '
        'JOIN app_naturalperson np ON np.id = ot.incharge_id '
        f'WHERE ot.otype_id IN ({ph2}) AND ot.incharge_id IS NOT NULL',
        params2,
    )
    _ensure_user_ids(ctx, incharge_users)


def _collect_positions_and_courses(ctx: SampleContext) -> None:
    # Only positions fully inside the sampled person/org sets.
    if ctx.person_ids and ctx.org_ids:
        ph_p, params_p = _in_clause(list(ctx.person_ids))
        ph_o, params_o = _in_clause(list(ctx.org_ids))
        ctx.position_ids |= _fetch_ids(
            f'SELECT id FROM app_position '
            f'WHERE person_id IN ({ph_p}) AND org_id IN ({ph_o})',
            list(params_p) + list(params_o),
        )

    # Courses owned by sampled orgs.
    if ctx.org_ids:
        ph, params = _in_clause(list(ctx.org_ids))
        ctx.course_ids |= _fetch_ids(
            f'SELECT id FROM app_course WHERE organization_id IN ({ph})',
            params,
        )
    if ctx.course_ids:
        ph, params = _in_clause(list(ctx.course_ids))
        ctx.coursetime_ids |= _fetch_ids(
            f'SELECT id FROM app_coursetime WHERE course_id IN ({ph})',
            params,
        )

    # Pending org/position applications tied to sampled users/persons.
    if ctx.user_ids and _table_exists('app_modifyorganization'):
        ph, params = _in_clause(list(ctx.user_ids))
        ctx.commentbase_ids |= _fetch_ids(
            f'SELECT commentbase_ptr_id FROM app_modifyorganization '
            f'WHERE pos_id IN ({ph})',
            params,
        )
    if ctx.person_ids and ctx.org_ids and _table_exists('app_modifyposition'):
        ph_p, params_p = _in_clause(list(ctx.person_ids))
        ph_o, params_o = _in_clause(list(ctx.org_ids))
        ctx.commentbase_ids |= _fetch_ids(
            f'SELECT commentbase_ptr_id FROM app_modifyposition '
            f'WHERE person_id IN ({ph_p}) AND org_id IN ({ph_o})',
            list(params_p) + list(params_o),
        )


def _collect_activities(ctx: SampleContext) -> None:
    if ctx.org_ids:
        ph, params = _in_clause(list(ctx.org_ids))
        ctx.activity_ids |= _fetch_ids(
            f'SELECT commentbase_ptr_id FROM app_activity '
            f'WHERE organization_id_id IN ({ph})',
            params,
        )
    if ctx.activity_ids:
        ph, params = _in_clause(list(ctx.activity_ids))
        ctx.commentbase_ids |= set(ctx.activity_ids)
        # Leaf-include examine teachers so FK rows remain valid.
        teacher_persons = _fetch_ids(
            f'SELECT examine_teacher_id FROM app_activity '
            f'WHERE commentbase_ptr_id IN ({ph}) '
            f'AND examine_teacher_id IS NOT NULL',
            params,
        )
        if teacher_persons:
            ctx.person_ids |= teacher_persons
            ph2, params2 = _in_clause(list(teacher_persons))
            _ensure_user_ids(
                ctx,
                _fetch_ids(
                    f'SELECT person_id_id FROM app_naturalperson '
                    f'WHERE id IN ({ph2})',
                    params2,
                ),
            )
        ctx.coursetime_ids |= _fetch_ids(
            f'SELECT course_time_id FROM app_activity '
            f'WHERE commentbase_ptr_id IN ({ph}) '
            f'AND course_time_id IS NOT NULL',
            params,
        )
        if ctx.coursetime_ids:
            ph2, params2 = _in_clause(list(ctx.coursetime_ids))
            ctx.course_ids |= _fetch_ids(
                f'SELECT course_id FROM app_coursetime WHERE id IN ({ph2})',
                params2,
            )


def _collect_appointments(ctx: SampleContext) -> None:
    unames = list(ctx.username_map)
    if unames:
        ph, params = _in_clause(unames)
        ctx.participant_usernames |= _fetch_ids(
            f'SELECT Sid_id FROM Appointment_participant '
            f'WHERE Sid_id IN ({ph})',
            params,
        )
    if not ctx.participant_usernames:
        return
    ph, params = _in_clause(list(ctx.participant_usernames))
    # Appointments owned by sampled participants.
    ctx.appoint_ids |= _fetch_ids(
        f'SELECT Aid FROM Appointment_appoint '
        f'WHERE major_student_id IN ({ph})',
        params,
    )
    if not ctx.appoint_ids:
        return
    ph_a, params_a = _in_clause(list(ctx.appoint_ids))
    # Leaf-include other students listed on those appointments.
    student_ids = _fetch_ids(
        f'SELECT participant_id FROM Appointment_appoint_students '
        f'WHERE appoint_id IN ({ph_a})',
        params_a,
    )
    ctx.participant_usernames |= student_ids
    _ensure_user_ids(
        ctx,
        User.objects.filter(username__in=student_ids).values_list(
            'id', flat=True
        ),
    )


def _collect_feedback_comments_notifications(ctx: SampleContext) -> None:
    if ctx.person_ids:
        ph, params = _in_clause(list(ctx.person_ids))
        ctx.feedback_ids |= _fetch_ids(
            f'SELECT commentbase_ptr_id FROM feedback_feedback '
            f'WHERE person_id IN ({ph})',
            params,
        )
    if ctx.org_ids:
        ph, params = _in_clause(list(ctx.org_ids))
        ctx.feedback_ids |= _fetch_ids(
            f'SELECT commentbase_ptr_id FROM feedback_feedback '
            f'WHERE org_id IN ({ph})',
            params,
        )
    # Org-sourced feedback may reference persons outside the user sample.
    # Leaf-include those persons (and their User rows) so person_id FKs stay
    # valid; Feedback.person is NOT NULL and cannot be nulled at write time.
    if ctx.feedback_ids and _table_exists('feedback_feedback'):
        ph, params = _in_clause(list(ctx.feedback_ids))
        feedback_persons = _fetch_ids(
            f'SELECT DISTINCT person_id FROM feedback_feedback '
            f'WHERE commentbase_ptr_id IN ({ph})',
            params,
        )
        if feedback_persons:
            ctx.person_ids |= feedback_persons
            ph2, params2 = _in_clause(list(feedback_persons))
            _ensure_user_ids(
                ctx,
                _fetch_ids(
                    f'SELECT person_id_id FROM app_naturalperson '
                    f'WHERE id IN ({ph2})',
                    params2,
                ),
            )
        # Drop feedback whose person still cannot be exported.
        if ctx.person_ids:
            ph_p, params_p = _in_clause(list(ctx.person_ids))
            valid = _fetch_ids(
                f'SELECT commentbase_ptr_id FROM feedback_feedback '
                f'WHERE commentbase_ptr_id IN ({ph}) '
                f'AND person_id IN ({ph_p})',
                params + params_p,
            )
        else:
            valid = set()
        drop = ctx.feedback_ids - valid
        ctx.feedback_ids -= drop
    ctx.commentbase_ids |= ctx.feedback_ids
    # Notifications are not exported (content often still contains PII).


def _collect_pools_academic_achievements(ctx: SampleContext) -> None:
    if ctx.user_ids:
        ph, params = _in_clause(list(ctx.user_ids))
        ctx.pool_ids |= _fetch_ids(
            f'SELECT DISTINCT pool_id FROM app_poolrecord '
            f'WHERE user_id IN ({ph})',
            params,
        )
    # Also include pools linked to sampled activities.
    if ctx.activity_ids and _table_exists('app_pool'):
        ph, params = _in_clause(list(ctx.activity_ids))
        ctx.pool_ids |= _fetch_ids(
            f'SELECT id FROM app_pool '
            f'WHERE activity_id IN ({ph})',
            params,
        )
    if ctx.pool_ids:
        ph, params = _in_clause(list(ctx.pool_ids))
        ctx.poolitem_ids |= _fetch_ids(
            f'SELECT id FROM app_poolitem WHERE pool_id IN ({ph})',
            params,
        )


def _collect_questionnaire(ctx: SampleContext) -> None:
    if not ctx.user_ids:
        return
    ph, params = _in_clause(list(ctx.user_ids))
    ctx.survey_ids |= _fetch_ids(
        f'SELECT id FROM questionnaire_survey WHERE creator_id IN ({ph})',
        params,
    )
    ctx.answersheet_ids |= _fetch_ids(
        f'SELECT id FROM questionnaire_answersheet WHERE creator_id IN ({ph})',
        params,
    )
    if ctx.answersheet_ids:
        ph2, params2 = _in_clause(list(ctx.answersheet_ids))
        ctx.survey_ids |= _fetch_ids(
            f'SELECT DISTINCT survey_id FROM questionnaire_answersheet '
            f'WHERE id IN ({ph2})',
            params2,
        )
        creators = _fetch_ids(
            f'SELECT DISTINCT creator_id FROM questionnaire_answersheet '
            f'WHERE id IN ({ph2})',
            params2,
        )
        _ensure_user_ids(ctx, creators)
    if ctx.survey_ids:
        ph2, params2 = _in_clause(list(ctx.survey_ids))
        ctx.question_ids |= _fetch_ids(
            f'SELECT id FROM questionnaire_question WHERE survey_id IN ({ph2})',
            params2,
        )
        _ensure_user_ids(
            ctx,
            _fetch_ids(
                f'SELECT creator_id FROM questionnaire_survey '
                f'WHERE id IN ({ph2})',
                params2,
            ),
        )


def _collect_library_dorm_logs(ctx: SampleContext) -> None:
    # Readers whose student_id matches old usernames in sample.
    unames = list(ctx.username_map)
    if unames:
        ph, params = _in_clause(unames)
        ctx.reader_ids |= _fetch_ids(
            f'SELECT id FROM yp_library_reader WHERE student_id IN ({ph})',
            params,
        )
    if ctx.reader_ids:
        ph, params = _in_clause(list(ctx.reader_ids))
        ctx.book_ids |= _fetch_ids(
            f'SELECT DISTINCT book_id_id FROM yp_library_lendrecord '
            f'WHERE reader_id_id IN ({ph}) AND book_id_id IS NOT NULL',
            params,
        )


def _collect_freshmen(ctx: SampleContext) -> None:
    ids = list(_fetch_ids('SELECT id FROM app_freshman'))
    if not ids:
        return
    rng = random.Random(ctx.seed + 1)
    count = max(1, int(len(ids) * ctx.ratio)) if len(ids) > 1 else len(ids)
    count = min(count, len(ids))
    ctx.freshman_ids = set(rng.sample(ids, count))


def _sql_literal(value: Any) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    if isinstance(value, time):
        return f"'{value.strftime('%H:%M:%S')}'"
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        hours, rem = divmod(abs(total), 3600)
        minutes, seconds = divmod(rem, 60)
        sign = '-' if total < 0 else ''
        return f"'{sign}{hours}:{minutes:02d}:{seconds:02d}'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return 'NULL'
    text = str(value)
    text = text.replace('\\', '\\\\').replace("'", "\\'")
    text = text.replace('\n', '\\n').replace('\r', '\\r')
    return f"'{text}'"


def _quote_ident(name: str) -> str:
    return f'`{name}`'


def _table_columns(table: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM {_quote_ident(table)} LIMIT 0')
        return [col[0] for col in cursor.description]


def _fetch_rows(
    table: str,
    columns: Sequence[str],
    where_sql: str | None = None,
    params: Sequence[Any] | None = None,
) -> list[tuple[Any, ...]]:
    col_sql = ', '.join(_quote_ident(c) for c in columns)
    sql = f'SELECT {col_sql} FROM {_quote_ident(table)}'
    if where_sql:
        sql += f' WHERE {where_sql}'
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return list(cursor.fetchall())


def _write_inserts(
    fh,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> None:
    if not rows:
        return
    col_list = ', '.join(_quote_ident(c) for c in columns)
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        fh.write(
            f'INSERT INTO {_quote_ident(table)} ({col_list}) VALUES\n'
        )
        values_lines = []
        for row in batch:
            rendered = ', '.join(_sql_literal(v) for v in row)
            values_lines.append(f'({rendered})')
        fh.write(',\n'.join(values_lines))
        fh.write(';\n')


def _transform_user_row(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    alias = ctx.user_by_id.get(int(data['id']))
    if alias is None:
        return None
    data['password'] = SAMPLE_PASSWORD_HASH
    data['username'] = alias.new_username
    data['first_name'] = ''
    data['last_name'] = ''
    data['email'] = alias.email
    data['name'] = alias.new_name
    data['pinyin'] = alias.pinyin
    data['acronym'] = alias.acronym
    # Avoid first-login password-change redirect when using the sample password.
    if 'is_newuser' in data:
        data['is_newuser'] = 0
    return tuple(data[c] for c in columns)


def _transform_naturalperson(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    alias = ctx.user_by_id.get(int(data['person_id_id']))
    if alias is None:
        return None
    data['stu_id_dbonly'] = alias.new_username
    data['name'] = alias.new_name
    data['nickname'] = alias.new_name
    data['birthday'] = None
    data['email'] = alias.email
    data['telephone'] = None
    data['biography'] = REDACTED
    data['avatar'] = ''
    data['wallpaper'] = ''
    data['QRcode'] = ''
    data['stu_dorm'] = None
    if data.get('stu_major') not in (None, ''):
        data['stu_major'] = REDACTED
    # stu_class is CharField(max_length=5); keep a short marker.
    if data.get('stu_class') not in (None, ''):
        data['stu_class'] = 'R'
    return tuple(data[c] for c in columns)


def _transform_organization(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    alias = ctx.user_by_id.get(int(data['organization_id_id']))
    if alias is None:
        return None
    # Prefer org series name from alias.
    data['oname'] = alias.new_name
    data['introduction'] = REDACTED
    data['avatar'] = ''
    data['QRcode'] = ''
    data['wallpaper'] = ''
    return tuple(data[c] for c in columns)


def _transform_freshman(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
    index_map: dict[int, int],
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    pk = int(data['id'])
    if pk not in index_map:
        return None
    n = index_map[pk]
    data['sid'] = f'F{n:06d}'
    data['name'] = f'新生{n}'
    data['birthday'] = date(2000, 1, 1)
    data['place'] = '其它'
    return tuple(data[c] for c in columns)


def _transform_participant(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    new_sid = ctx.username_map.get(str(data['Sid_id']))
    if new_sid is None:
        return None
    data['Sid_id'] = new_sid
    return tuple(data[c] for c in columns)


def _transform_appoint(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    major = ctx.username_map.get(str(data['major_student_id']))
    if major is None:
        return None
    data['major_student_id'] = major
    data['Ausage'] = USAGE_SAMPLE
    data['Aannouncement'] = ''
    return tuple(data[c] for c in columns)


def _generic_username_fields_transform(
    ctx: SampleContext,
    columns: Sequence[str],
    row: Sequence[Any],
    username_fields: Sequence[str],
    redact_fields: Sequence[str] = (),
    empty_fields: Sequence[str] = (),
) -> tuple[Any, ...] | None:
    data = dict(zip(columns, row))
    for field_name in username_fields:
        if field_name not in data:
            continue
        old = data[field_name]
        if old is None:
            continue
        mapped = ctx.username_map.get(str(old))
        if mapped is None:
            return None
        data[field_name] = mapped
    for field_name in redact_fields:
        if field_name in data and data[field_name] not in (None, ''):
            data[field_name] = REDACTED
    for field_name in empty_fields:
        if field_name in data:
            data[field_name] = '' if data[field_name] is not None else None
    return tuple(data[c] for c in columns)


def _write_full_table(fh, table: str) -> None:
    columns = _table_columns(table)
    rows = _fetch_rows(table, columns)
    # OrganizationType.incharge may reference persons outside sample; null out
    # missing incharge when exporting full orgtype after persons are known.
    _write_inserts(fh, table, columns, rows)


def _write_filtered(
    fh,
    table: str,
    where_sql: str,
    params: Sequence[Any],
    transform: Callable[
        [Sequence[str], Sequence[Any]],
        tuple[Any, ...] | None,
    ],
) -> None:
    columns = _table_columns(table)
    raw_rows = _fetch_rows(table, columns, where_sql, params)
    out_rows = []
    for row in raw_rows:
        transformed = transform(columns, row)
        if transformed is not None:
            out_rows.append(transformed)
    _write_inserts(fh, table, columns, out_rows)


def _write_all_tables(fh, ctx: SampleContext) -> None:
    # 1) Full configuration tables (fix orgtype incharge after persons exist:
    #    write orgtype later with adjusted incharge).
    for table in FULL_TABLES:
        if table == 'app_organizationtype':
            continue
        if not _table_exists(table):
            continue
        _write_full_table(fh, table)

    # Organization types with incharge restricted to sampled persons.
    if _table_exists('app_organizationtype'):
        columns = _table_columns('app_organizationtype')
        rows = _fetch_rows('app_organizationtype', columns)
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            incharge = data.get('incharge_id')
            if incharge is not None and int(incharge) not in ctx.person_ids:
                # Keep row; point incharge to NULL if person not retained.
                # But person_ids should include all incharge after expansion.
                if int(incharge) not in ctx.person_ids:
                    data['incharge_id'] = None
            out.append(tuple(data[c] for c in columns))
        # Re-fetch person_ids after expansion should include incharge; if still
        # missing, null them.
        fixed = []
        for row in out:
            data = dict(zip(columns, row))
            incharge = data.get('incharge_id')
            if incharge is not None and int(incharge) not in ctx.person_ids:
                data['incharge_id'] = None
            fixed.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_organizationtype', columns, fixed)

    # Feedback types: keep all rows, but null org defaults not in the sample.
    if _table_exists('feedback_feedbacktype'):
        columns = _table_columns('feedback_feedbacktype')
        rows = _fetch_rows('feedback_feedbacktype', columns)
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            org_id = data.get('org_id')
            if org_id is not None and int(org_id) not in ctx.org_ids:
                data['org_id'] = None
                # ALL_DEFAULT(2) claims both org and org_type defaults.
                if int(data.get('flexible') or 0) == 2:
                    if data.get('org_type_id') is not None:
                        data['flexible'] = 1  # ORG_TYPE_DEFAULT
                    else:
                        data['flexible'] = 0  # NO_DEFAULT
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'feedback_feedbacktype', columns, out)

    # College announcements: keep rows, redact message body.
    if _table_exists('Appointment_college_announcement'):
        columns = _table_columns('Appointment_college_announcement')
        rows = _fetch_rows('Appointment_college_announcement', columns)
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if data.get('announcement') not in (None, ''):
                data['announcement'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'Appointment_college_announcement', columns, out)

    # Books referenced by sample lend records (plus full if none).
    if _table_exists('yp_library_book'):
        columns = _table_columns('yp_library_book')
        if ctx.book_ids:
            ph, params = _in_clause(list(ctx.book_ids))
            rows = _fetch_rows(
                'yp_library_book', columns, f'id IN ({ph})', params
            )
        else:
            rows = []
        book_index = {
            int(dict(zip(columns, row))['id']): i
            for i, row in enumerate(
                sorted(rows, key=lambda r: int(dict(zip(columns, r))['id'])),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            n = book_index[int(data['id'])]
            data['title'] = f'书本{n}'
            if 'identity_code' in data:
                data['identity_code'] = f'B{n:06d}'
            if 'author' in data and data['author'] not in (None, ''):
                data['author'] = REDACTED
            if 'publisher' in data and data['publisher'] not in (None, ''):
                data['publisher'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'yp_library_book', columns, out)

    # Users and profiles
    if ctx.user_ids:
        ph, params = _in_clause(list(ctx.user_ids))
        _write_filtered(
            fh,
            'generic_user',
            f'id IN ({ph})',
            params,
            lambda cols, row: _transform_user_row(ctx, cols, row),
        )
    if ctx.person_ids:
        ph, params = _in_clause(list(ctx.person_ids))
        _write_filtered(
            fh,
            'app_naturalperson',
            f'id IN ({ph})',
            params,
            lambda cols, row: _transform_naturalperson(ctx, cols, row),
        )
    if ctx.org_ids:
        ph, params = _in_clause(list(ctx.org_ids))
        _write_filtered(
            fh,
            'app_organization',
            f'id IN ({ph})',
            params,
            lambda cols, row: _transform_organization(ctx, cols, row),
        )

    # Freshmen
    if ctx.freshman_ids and _table_exists('app_freshman'):
        ordered = sorted(ctx.freshman_ids)
        index_map = {pk: i for i, pk in enumerate(ordered, start=1)}
        ph, params = _in_clause(ordered)
        _write_filtered(
            fh,
            'app_freshman',
            f'id IN ({ph})',
            params,
            lambda cols, row: _transform_freshman(ctx, cols, row, index_map),
        )

    # Participants
    if ctx.participant_usernames:
        ph, params = _in_clause(list(ctx.participant_usernames))
        _write_filtered(
            fh,
            'Appointment_participant',
            f'Sid_id IN ({ph})',
            params,
            lambda cols, row: _transform_participant(ctx, cols, row),
        )

    # Credit / YQPoint by username; redact free-text source labels.
    for table, user_col in (
        ('generic_creditrecord', 'user_id'),
        ('generic_yqpointrecord', 'user_id'),
    ):
        if not _table_exists(table) or not ctx.username_map:
            continue
        ph, params = _in_clause(list(ctx.username_map))
        _write_filtered(
            fh,
            table,
            f'{_quote_ident(user_col)} IN ({ph})',
            params,
            lambda cols, row, uc=user_col: _generic_username_fields_transform(
                ctx, cols, row, [uc], redact_fields=['source'],
            ),
        )

    # M2M org tags / unsubscribe
    if ctx.org_ids and _table_exists('app_organization_tags'):
        ph, params = _in_clause(list(ctx.org_ids))
        columns = _table_columns('app_organization_tags')
        rows = _fetch_rows(
            'app_organization_tags',
            columns,
            f'organization_id IN ({ph})',
            params,
        )
        _write_inserts(fh, 'app_organization_tags', columns, rows)

    if ctx.person_ids and _table_exists('app_naturalperson_unsubscribe_list'):
        ph, params = _in_clause(list(ctx.person_ids))
        columns = _table_columns('app_naturalperson_unsubscribe_list')
        # Keep rows where person is sampled; org side may need sampled org.
        rows = _fetch_rows(
            'app_naturalperson_unsubscribe_list',
            columns,
            f'naturalperson_id IN ({ph})',
            params,
        )
        if 'organization_id' in columns:
            idx = columns.index('organization_id')
            rows = [r for r in rows if r[idx] in ctx.org_ids]
        _write_inserts(
            fh, 'app_naturalperson_unsubscribe_list', columns, rows
        )

    # Courses / course times
    if ctx.course_ids and _table_exists('app_course'):
        ph, params = _in_clause(list(ctx.course_ids))
        columns = _table_columns('app_course')
        rows = _fetch_rows('app_course', columns, f'id IN ({ph})', params)
        # Stable numbering by primary key among exported courses.
        course_index = {
            int(dict(zip(columns, row))['id']): i
            for i, row in enumerate(
                sorted(rows, key=lambda r: int(dict(zip(columns, r))['id'])),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            data['name'] = f'课程{course_index[int(data["id"])]}'
            if 'teacher' in data and data['teacher'] not in (None, ''):
                data['teacher'] = REDACTED
            if 'classroom' in data and data['classroom'] not in (None, ''):
                data['classroom'] = REDACTED
            for key in (
                'introduction', 'teaching_plan', 'record_cal_method',
            ):
                if key in data and data[key] not in (None, ''):
                    data[key] = REDACTED
            if 'photo' in data:
                data['photo'] = ''
            if 'QRcode' in data:
                data['QRcode'] = ''
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_course', columns, out)

    if ctx.coursetime_ids and _table_exists('app_coursetime'):
        ph, params = _in_clause(list(ctx.coursetime_ids))
        columns = _table_columns('app_coursetime')
        rows = _fetch_rows(
            'app_coursetime', columns, f'id IN ({ph})', params
        )
        _write_inserts(fh, 'app_coursetime', columns, rows)

    # CommentBase for activities/feedback
    if ctx.commentbase_ids and _table_exists('app_commentbase'):
        ph, params = _in_clause(list(ctx.commentbase_ids))
        columns = _table_columns('app_commentbase')
        rows = _fetch_rows(
            'app_commentbase', columns, f'id IN ({ph})', params
        )
        _write_inserts(fh, 'app_commentbase', columns, rows)

    if ctx.activity_ids and _table_exists('app_activity'):
        ph, params = _in_clause(list(ctx.activity_ids))
        columns = _table_columns('app_activity')
        rows = _fetch_rows(
            'app_activity', columns, f'commentbase_ptr_id IN ({ph})', params
        )
        activity_index = {
            int(dict(zip(columns, row))['commentbase_ptr_id']): i
            for i, row in enumerate(
                sorted(
                    rows,
                    key=lambda r: int(
                        dict(zip(columns, r))['commentbase_ptr_id']
                    ),
                ),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            pk = int(data['commentbase_ptr_id'])
            data['title'] = f'活动{activity_index[pk]}'
            data['introduction'] = REDACTED
            if data.get('location') not in (None, ''):
                data['location'] = REDACTED
            if 'QRcode' in data:
                data['QRcode'] = ''
            if 'URL' in data:
                data['URL'] = ''
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_activity', columns, out)

    # Prizes (full table, names anonymized); write before pool items reference them.
    if _table_exists('app_prize'):
        columns = _table_columns('app_prize')
        rows = _fetch_rows('app_prize', columns)
        prize_index = {
            int(dict(zip(columns, row))['id']): i
            for i, row in enumerate(
                sorted(rows, key=lambda r: int(dict(zip(columns, r))['id'])),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            data['name'] = f'奖品{prize_index[int(data["id"])]}'
            if data.get('more_info') not in (None, ''):
                data['more_info'] = REDACTED
            if 'image' in data:
                data['image'] = ''
            provider = data.get('provider_id')
            if provider is not None and int(provider) not in ctx.user_ids:
                data['provider_id'] = None
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_prize', columns, out)

    if ctx.pool_ids and _table_exists('app_pool'):
        ph, params = _in_clause(list(ctx.pool_ids))
        columns = _table_columns('app_pool')
        rows = _fetch_rows('app_pool', columns, f'id IN ({ph})', params)
        pool_index = {
            int(dict(zip(columns, row))['id']): i
            for i, row in enumerate(
                sorted(rows, key=lambda r: int(dict(zip(columns, r))['id'])),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            data['title'] = f'奖池{pool_index[int(data["id"])]}'
            # Pools may be kept via pool records while the linked activity
            # was not sampled; null dangling FKs so import stays consistent.
            activity_id = data.get('activity_id')
            if (
                activity_id is not None
                and int(activity_id) not in ctx.activity_ids
            ):
                data['activity_id'] = None
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_pool', columns, out)

    if ctx.poolitem_ids and _table_exists('app_poolitem'):
        ph, params = _in_clause(list(ctx.poolitem_ids))
        columns = _table_columns('app_poolitem')
        rows = _fetch_rows('app_poolitem', columns, f'id IN ({ph})', params)
        _write_inserts(fh, 'app_poolitem', columns, rows)

    if ctx.activity_ids and _table_exists('app_activityphoto'):
        ph, params = _in_clause(list(ctx.activity_ids))
        columns = _table_columns('app_activityphoto')
        rows = _fetch_rows(
            'app_activityphoto', columns, f'activity_id IN ({ph})', params
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if 'image' in data:
                data['image'] = ''
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_activityphoto', columns, out)

    if ctx.activity_ids and _table_exists('app_activitysummary'):
        ph, params = _in_clause(list(ctx.activity_ids))
        columns = _table_columns('app_activitysummary')
        rows = _fetch_rows(
            'app_activitysummary', columns, f'activity_id IN ({ph})', params
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if 'image' in data:
                data['image'] = ''
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_activitysummary', columns, out)

    # Participation: person in sample AND activity in sample
    if (
        ctx.person_ids and ctx.activity_ids
        and _table_exists('app_participation')
    ):
        ph_p, params_p = _in_clause(list(ctx.person_ids))
        ph_a, params_a = _in_clause(list(ctx.activity_ids))
        columns = _table_columns('app_participation')
        rows = _fetch_rows(
            'app_participation',
            columns,
            f'person_id IN ({ph_p}) AND activity_id IN ({ph_a})',
            list(params_p) + list(params_a),
        )
        _write_inserts(fh, 'app_participation', columns, rows)

    if ctx.position_ids and _table_exists('app_position'):
        ph, params = _in_clause(list(ctx.position_ids))
        # Only positions whose person and org are both retained.
        columns = _table_columns('app_position')
        rows = _fetch_rows('app_position', columns, f'id IN ({ph})', params)
        rows = [
            r for r in rows
            if dict(zip(columns, r)).get('person_id') in ctx.person_ids
            and dict(zip(columns, r)).get('org_id') in ctx.org_ids
        ]
        _write_inserts(fh, 'app_position', columns, rows)

    if ctx.course_ids and ctx.person_ids and _table_exists('app_courseparticipant'):
        ph_c, params_c = _in_clause(list(ctx.course_ids))
        ph_p, params_p = _in_clause(list(ctx.person_ids))
        columns = _table_columns('app_courseparticipant')
        rows = _fetch_rows(
            'app_courseparticipant',
            columns,
            f'course_id IN ({ph_c}) AND person_id IN ({ph_p})',
            list(params_c) + list(params_p),
        )
        _write_inserts(fh, 'app_courseparticipant', columns, rows)

    if ctx.person_ids and _table_exists('app_courserecord'):
        ph, params = _in_clause(list(ctx.person_ids))
        columns = _table_columns('app_courserecord')
        rows = _fetch_rows(
            'app_courserecord', columns, f'person_id IN ({ph})', params
        )
        # Always filter course_id when the column exists. An empty
        # ctx.course_ids means keep only NULL (no sampled courses written).
        if 'course_id' in columns:
            idx = columns.index('course_id')
            rows = [
                r for r in rows
                if r[idx] is None or r[idx] in ctx.course_ids
            ]
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if data.get('extra_name') not in (None, ''):
                data['extra_name'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_courserecord', columns, out)

    if ctx.feedback_ids and _table_exists('feedback_feedback'):
        ph, params = _in_clause(list(ctx.feedback_ids))
        columns = _table_columns('feedback_feedback')
        rows = _fetch_rows(
            'feedback_feedback',
            columns,
            f'commentbase_ptr_id IN ({ph})',
            params,
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            person_id = data.get('person_id')
            # NOT NULL FK: skip rather than null when the person was not sampled.
            if person_id is None or int(person_id) not in ctx.person_ids:
                continue
            for key in ('title', 'content'):
                if key in data and data[key] not in (None, ''):
                    data[key] = REDACTED
            if 'url' in data:
                data['url'] = ''
            org_id = data.get('org_id')
            if org_id is not None and int(org_id) not in ctx.org_ids:
                data['org_id'] = None
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'feedback_feedback', columns, out)

    # Modify organization / position applications
    if ctx.user_ids and _table_exists('app_modifyorganization'):
        ph, params = _in_clause(list(ctx.user_ids))
        columns = _table_columns('app_modifyorganization')
        rows = _fetch_rows(
            'app_modifyorganization',
            columns,
            f'pos_id IN ({ph})',
            params,
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            data['oname'] = REDACTED
            if data.get('introduction') not in (None, ''):
                data['introduction'] = REDACTED
            if data.get('application') not in (None, ''):
                data['application'] = REDACTED
            if 'avatar' in data:
                data['avatar'] = ''
            # Ensure commentbase parent was exported.
            if data.get('commentbase_ptr_id') not in ctx.commentbase_ids:
                continue
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_modifyorganization', columns, out)

    if (
        ctx.person_ids and ctx.org_ids
        and _table_exists('app_modifyposition')
    ):
        ph_p, params_p = _in_clause(list(ctx.person_ids))
        ph_o, params_o = _in_clause(list(ctx.org_ids))
        columns = _table_columns('app_modifyposition')
        rows = _fetch_rows(
            'app_modifyposition',
            columns,
            f'person_id IN ({ph_p}) AND org_id IN ({ph_o})',
            list(params_p) + list(params_o),
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if data.get('commentbase_ptr_id') not in ctx.commentbase_ids:
                continue
            if data.get('reason') not in (None, ''):
                data['reason'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_modifyposition', columns, out)

    if ctx.commentbase_ids and _table_exists('app_comment'):
        ph, params = _in_clause(list(ctx.commentbase_ids))
        columns = _table_columns('app_comment')
        rows = _fetch_rows(
            'app_comment', columns, f'commentbase_id IN ({ph})', params
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if data.get('commentator_id') not in ctx.user_ids:
                continue
            if data.get('text') not in (None, ''):
                data['text'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_comment', columns, out)
        comment_ids = {
            dict(zip(columns, r))['id'] for r in out
        } if out and 'id' in columns else set()
        if comment_ids and _table_exists('app_commentphoto'):
            ph2, params2 = _in_clause(list(comment_ids))
            pcols = _table_columns('app_commentphoto')
            prows = _fetch_rows(
                'app_commentphoto', pcols, f'comment_id IN ({ph2})', params2
            )
            pout = []
            for row in prows:
                data = dict(zip(pcols, row))
                if 'image' in data:
                    data['image'] = ''
                pout.append(tuple(data[c] for c in pcols))
            _write_inserts(fh, 'app_commentphoto', pcols, pout)

    # app_notification is intentionally omitted from sample dumps.

    if ctx.person_ids and _table_exists('app_academictagentry'):
        ph, params = _in_clause(list(ctx.person_ids))
        columns = _table_columns('app_academictagentry')
        # person_id on AcademicEntry
        person_col = 'person_id' if 'person_id' in columns else None
        if person_col:
            rows = _fetch_rows(
                'app_academictagentry',
                columns,
                f'{_quote_ident(person_col)} IN ({ph})',
                params,
            )
            _write_inserts(fh, 'app_academictagentry', columns, rows)

    if ctx.person_ids and _table_exists('app_academictextentry'):
        ph, params = _in_clause(list(ctx.person_ids))
        columns = _table_columns('app_academictextentry')
        rows = _fetch_rows(
            'app_academictextentry',
            columns,
            f'person_id IN ({ph})',
            params,
        )
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if data.get('content') not in (None, ''):
                data['content'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'app_academictextentry', columns, out)

    if ctx.user_ids and _table_exists('app_academicqaawards'):
        ph, params = _in_clause(list(ctx.user_ids))
        columns = _table_columns('app_academicqaawards')
        rows = _fetch_rows(
            'app_academicqaawards', columns, f'user_id IN ({ph})', params
        )
        _write_inserts(fh, 'app_academicqaawards', columns, rows)

    if ctx.user_ids and ctx.pool_ids and _table_exists('app_poolrecord'):
        ph_u, params_u = _in_clause(list(ctx.user_ids))
        ph_p, params_p = _in_clause(list(ctx.pool_ids))
        columns = _table_columns('app_poolrecord')
        rows = _fetch_rows(
            'app_poolrecord',
            columns,
            f'user_id IN ({ph_u}) AND pool_id IN ({ph_p})',
            list(params_u) + list(params_p),
        )
        _write_inserts(fh, 'app_poolrecord', columns, rows)

    if ctx.user_ids and _table_exists('achievement_achievementunlock'):
        ph, params = _in_clause(list(ctx.user_ids))
        columns = _table_columns('achievement_achievementunlock')
        rows = _fetch_rows(
            'achievement_achievementunlock',
            columns,
            f'user_id IN ({ph})',
            params,
        )
        _write_inserts(fh, 'achievement_achievementunlock', columns, rows)

    if ctx.username_map and _table_exists('app_modifyrecord'):
        ph, params = _in_clause(list(ctx.username_map))
        _write_filtered(
            fh,
            'app_modifyrecord',
            f'user_id IN ({ph})',
            params,
            lambda cols, row: _generic_username_fields_transform(
                ctx, cols, row, ['user_id'],
                redact_fields=['name', 'info'],
            ),
        )

    # Dormitory agreements only for retained users.
    if ctx.user_ids and _table_exists('dormitory_agreement'):
        ph, params = _in_clause(list(ctx.user_ids))
        columns = _table_columns('dormitory_agreement')
        rows = _fetch_rows(
            'dormitory_agreement',
            columns,
            f'user_id IN ({ph})',
            params,
        )
        _write_inserts(fh, 'dormitory_agreement', columns, rows)

    if ctx.user_ids and _table_exists('dormitory_dormitoryassignment'):
        ph, params = _in_clause(list(ctx.user_ids))
        columns = _table_columns('dormitory_dormitoryassignment')
        rows = _fetch_rows(
            'dormitory_dormitoryassignment',
            columns,
            f'user_id IN ({ph})',
            params,
        )
        _write_inserts(fh, 'dormitory_dormitoryassignment', columns, rows)

    # Appointments
    if ctx.appoint_ids:
        ph, params = _in_clause(list(ctx.appoint_ids))
        _write_filtered(
            fh,
            'Appointment_appoint',
            f'Aid IN ({ph})',
            params,
            lambda cols, row: _transform_appoint(ctx, cols, row),
        )
        # M2M students
        if _table_exists('Appointment_appoint_students'):
            columns = _table_columns('Appointment_appoint_students')
            rows = _fetch_rows(
                'Appointment_appoint_students',
                columns,
                f'appoint_id IN ({ph})',
                params,
            )
            out = []
            for row in rows:
                data = dict(zip(columns, row))
                mapped = ctx.username_map.get(str(data['participant_id']))
                if mapped is None:
                    continue
                data['participant_id'] = mapped
                out.append(tuple(data[c] for c in columns))
            _write_inserts(fh, 'Appointment_appoint_students', columns, out)

        if _table_exists('Appointment_longtermappoint'):
            columns = _table_columns('Appointment_longtermappoint')
            rows = _fetch_rows(
                'Appointment_longtermappoint',
                columns,
                f'appoint_id IN ({ph})',
                params,
            )
            out = []
            for row in rows:
                data = dict(zip(columns, row))
                if 'applicant_id' in data:
                    mapped = ctx.username_map.get(str(data['applicant_id']))
                    if mapped is None:
                        continue
                    data['applicant_id'] = mapped
                if data.get('review_comment'):
                    data['review_comment'] = REDACTED
                out.append(tuple(data[c] for c in columns))
            _write_inserts(fh, 'Appointment_longtermappoint', columns, out)

    if ctx.participant_usernames and _table_exists('Appointment_cardcheckinfo'):
        ph, params = _in_clause(list(ctx.participant_usernames))
        _write_filtered(
            fh,
            'Appointment_cardcheckinfo',
            f'Cardstudent_id IN ({ph})',
            params,
            lambda cols, row: _generic_username_fields_transform(
                ctx, cols, row, ['Cardstudent_id'],
                redact_fields=['Message'],
            ),
        )

    # Questionnaire (titles/topics/choices are free text; anonymize).
    if ctx.survey_ids and _table_exists('questionnaire_survey'):
        ph, params = _in_clause(list(ctx.survey_ids))
        columns = _table_columns('questionnaire_survey')
        rows = _fetch_rows(
            'questionnaire_survey', columns, f'id IN ({ph})', params
        )
        survey_index = {
            int(dict(zip(columns, row))['id']): i
            for i, row in enumerate(
                sorted(rows, key=lambda r: int(dict(zip(columns, r))['id'])),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            if data.get('creator_id') not in ctx.user_ids:
                continue
            data['title'] = f'问卷{survey_index[int(data["id"])]}'
            if data.get('description') not in (None, ''):
                data['description'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'questionnaire_survey', columns, out)

    if ctx.question_ids and _table_exists('questionnaire_question'):
        ph, params = _in_clause(list(ctx.question_ids))
        columns = _table_columns('questionnaire_question')
        rows = _fetch_rows(
            'questionnaire_question', columns, f'id IN ({ph})', params
        )
        question_index = {
            int(dict(zip(columns, row))['id']): i
            for i, row in enumerate(
                sorted(rows, key=lambda r: int(dict(zip(columns, r))['id'])),
                start=1,
            )
        }
        out = []
        for row in rows:
            data = dict(zip(columns, row))
            data['topic'] = f'题目{question_index[int(data["id"])]}'
            if data.get('description') not in (None, ''):
                data['description'] = REDACTED
            out.append(tuple(data[c] for c in columns))
        _write_inserts(fh, 'questionnaire_question', columns, out)
        if _table_exists('questionnaire_choice'):
            pcols = _table_columns('questionnaire_choice')
            prows = _fetch_rows(
                'questionnaire_choice',
                pcols,
                f'question_id IN ({ph})',
                params,
            )
            pout = []
            for row in prows:
                data = dict(zip(pcols, row))
                if data.get('text') not in (None, ''):
                    data['text'] = REDACTED
                pout.append(tuple(data[c] for c in pcols))
            _write_inserts(fh, 'questionnaire_choice', pcols, pout)

    if ctx.answersheet_ids and _table_exists('questionnaire_answersheet'):
        ph, params = _in_clause(list(ctx.answersheet_ids))
        columns = _table_columns('questionnaire_answersheet')
        rows = _fetch_rows(
            'questionnaire_answersheet', columns, f'id IN ({ph})', params
        )
        rows = [
            r for r in rows
            if dict(zip(columns, r)).get('creator_id') in ctx.user_ids
        ]
        _write_inserts(fh, 'questionnaire_answersheet', columns, rows)
        if _table_exists('questionnaire_answertext'):
            pcols = _table_columns('questionnaire_answertext')
            prows = _fetch_rows(
                'questionnaire_answertext',
                pcols,
                f'answersheet_id IN ({ph})',
                params,
            )
            pout = []
            for row in prows:
                data = dict(zip(pcols, row))
                if data.get('body') not in (None, ''):
                    data['body'] = REDACTED
                pout.append(tuple(data[c] for c in pcols))
            _write_inserts(fh, 'questionnaire_answertext', pcols, pout)

    # Library
    if ctx.reader_ids and _table_exists('yp_library_reader'):
        ph, params = _in_clause(list(ctx.reader_ids))
        reader_columns = _table_columns('yp_library_reader')
        reader_rows = _fetch_rows(
            'yp_library_reader',
            reader_columns,
            f'id IN ({ph})',
            params,
        )
        # Production reader.id values come from the external library DB and
        # must not appear in committed sample dumps. Remap to 1..N by old id.
        reader_index = {
            int(dict(zip(reader_columns, row))['id']): i
            for i, row in enumerate(
                sorted(
                    reader_rows,
                    key=lambda r: int(dict(zip(reader_columns, r))['id']),
                ),
                start=1,
            )
        }
        reader_out = []
        for row in reader_rows:
            transformed = _generic_username_fields_transform(
                ctx, reader_columns, row, ['student_id']
            )
            if transformed is None:
                continue
            data = dict(zip(reader_columns, transformed))
            old_id = int(dict(zip(reader_columns, row))['id'])
            if old_id not in reader_index:
                continue
            data['id'] = reader_index[old_id]
            reader_out.append(tuple(data[c] for c in reader_columns))
        _write_inserts(fh, 'yp_library_reader', reader_columns, reader_out)

        if _table_exists('yp_library_lendrecord'):
            lend_columns = _table_columns('yp_library_lendrecord')
            # FK column names: reader_id_id / book_id_id from Django.
            reader_col = (
                'reader_id_id' if 'reader_id_id' in lend_columns
                else 'reader_id'
            )
            lend_rows = _fetch_rows(
                'yp_library_lendrecord',
                lend_columns,
                f'{_quote_ident(reader_col)} IN ({ph})',
                params,
            )
            lend_data_rows: list[dict[str, Any]] = []
            for row in lend_rows:
                data = dict(zip(lend_columns, row))
                old_reader = data.get(reader_col)
                if (
                    old_reader is None
                    or int(old_reader) not in reader_index
                ):
                    continue
                data[reader_col] = reader_index[int(old_reader)]
                lend_data_rows.append(data)
            # Remap lendrecord PKs so external library record IDs are not kept.
            lend_data_rows.sort(key=lambda d: int(d['id']))
            lend_out = []
            for i, data in enumerate(lend_data_rows, start=1):
                data['id'] = i
                lend_out.append(tuple(data[c] for c in lend_columns))
            _write_inserts(
                fh, 'yp_library_lendrecord', lend_columns, lend_out
            )

    # Page/module tracking logs are omitted: they are bulky access trails and
    # may contain client fingerprint fields (platform / browser version).


def _table_exists(table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT 1 FROM information_schema.tables '
            'WHERE table_schema = DATABASE() AND table_name = %s',
            [table],
        )
        return cursor.fetchone() is not None
