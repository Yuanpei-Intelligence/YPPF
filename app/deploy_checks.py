"""
Website app checks of ``python manage.py deploy_check``.

Course selection (the ``course`` election windows, auditors and prerequisite
survey) and YQPoint (sign-in and activity rewards, the YQPoint organization).
Database reads only. Level policy: ``utils.deploy_check``.
"""
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Iterator

from django.core.exceptions import ImproperlyConfigured

from utils.config.cast import str_to_time
from utils.deploy_check import (
    FAIL, OK, WARN, is_blank, production_level, resolve_setting,
)
from utils.health_check import db_connection_healthy
from questionnaire.models import Survey
from app.config import CONFIG
from app.course_survey_utils import get_course_prerequisite_survey
from app.models import NaturalPerson, Organization


__all__ = ['checks']


Result = tuple[str, str, str]

# The stages that register_selection() schedules, in the order they must run.
ELECTION_STAGES = (
    'yx_election_start',
    'yx_election_end',
    'publish_time',
    'btx_election_start',
    'btx_election_end',
)
ACTIVITY_REWARD_SETTINGS = ('invalid_hour', 'per_hour', 'max')


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the course selection and YQPoint checks."""
    yield _check_election_windows(datetime.now())
    yield _check_yqpoint_rewards()
    if not db_connection_healthy():
        yield WARN, 'course and YQPoint data', 'skipped: database unreachable'
        return
    yield _check_auditors()
    yield _check_prerequisite_survey()
    yield _check_yqpoint_organization()


def _check_election_windows(now: datetime) -> Result:
    name = 'course election windows'
    times: list[datetime] = []
    invalid = []
    for stage in ELECTION_STAGES:
        raw, _ = resolve_setting(CONFIG.course, stage)
        try:
            times.append(str_to_time(raw))
        except (TypeError, ValueError):
            invalid.append(f'course.{stage}')
    if invalid:
        return (FAIL, name, f'{", ".join(invalid)} missing or not a time: '
                'launching course selection fails')
    # When a course is launched, register_selection() schedules every stage
    # that has already passed a few seconds after the launch, in stage order.
    # Only a stage still in the future that is later than its successor can
    # therefore run out of order.
    for index in range(len(ELECTION_STAGES) - 1):
        if max(times[index], now) > max(times[index + 1], now):
            return (FAIL, name, f'course.{ELECTION_STAGES[index]} '
                    f'({times[index]:%Y-%m-%d %H:%M}) is later than '
                    f'course.{ELECTION_STAGES[index + 1]} '
                    f'({times[index + 1]:%Y-%m-%d %H:%M}): the stages would '
                    'run out of order')
    upcoming = [
        (stage, time) for stage, time in zip(ELECTION_STAGES, times) if time > now
    ]
    if upcoming:
        stage, time = upcoming[0]
        return OK, name, f'ordered; next is course.{stage} at {time:%Y-%m-%d %H:%M}'
    return OK, name, 'ordered; all in the past'


def _check_yqpoint_rewards() -> Result:
    name = 'YQPoint rewards'
    invalid = []
    points, error = resolve_setting(CONFIG.yqpoint, 'signin_points')
    if error or not _valid_signin_points(points):
        invalid.append('YQPoint.signin_points')
    for attr in ACTIVITY_REWARD_SETTINGS:
        _, error = resolve_setting(CONFIG.yqpoint.activity, attr)
        if error:
            invalid.append(f'YQPoint.activity.{attr}')
    if invalid:
        return (FAIL, name, f'invalid {", ".join(invalid)}: sign-in and activity '
                'rewards fail')
    return OK, name, f'{len(points)}-day sign-in cycle'


def _valid_signin_points(points: Any) -> bool:
    # Each day grants a fixed count or a random count in [low, high].
    if not isinstance(points, (list, tuple)) or not points:
        return False
    for point in points:
        if _is_count(point):
            continue
        if (isinstance(point, (list, tuple)) and len(point) == 2
                and all(_is_count(bound) for bound in point)
                and point[0] <= point[1]):
            continue
        return False
    return True


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_auditors() -> Result:
    name = 'course.auditors'
    auditors, error = resolve_setting(CONFIG.course, 'audit_teachers')
    if error or not auditors:
        return FAIL, name, 'missing or empty: course activities cannot be created'
    try:
        NaturalPerson.objects.get_teacher(auditors[0])
    except (NaturalPerson.DoesNotExist,
            NaturalPerson.MultipleObjectsReturned) as exc:
        return (production_level(), name, 'the first auditor does not match '
                f'exactly one active teacher ({type(exc).__name__}): course '
                'activities cannot be created')
    return OK, name, f'{len(auditors)} configured; the first matches a teacher'


def _check_prerequisite_survey() -> Result:
    name = 'course.prerequisite_survey'
    config, error = resolve_setting(CONFIG.course, 'prerequisite_survey')
    if error is None and config.get('enabled', False) is False:
        return OK, name, 'disabled'
    try:
        # Validates the flag, every rule and pattern, and the fallback title.
        get_course_prerequisite_survey(SimpleNamespace(username=''))
    except ImproperlyConfigured as exc:
        survey_lookup = isinstance(
            exc.__cause__,
            (Survey.DoesNotExist, Survey.MultipleObjectsReturned))
        if not survey_lookup:
            return FAIL, name, f'{exc}: course selection fails closed'
    titles = list(dict.fromkeys(
        [rule['survey'] for rule in config.get('rules', [])]
        + [config['fallback']]))
    unresolved = [
        title for title in titles
        if Survey.objects.filter(title=title).count() != 1
    ]
    if unresolved:
        return (FAIL, name, 'no single survey titled '
                f'{", ".join(map(repr, unresolved))}: course selection fails '
                'closed for matching students')
    return OK, name, f'enabled; all {len(titles)} survey title(s) resolve'


def _check_yqpoint_organization() -> Result:
    name = 'YQPoint.org_name'
    org_name, error = resolve_setting(CONFIG.yqpoint, 'org_name')
    if error or is_blank(org_name):
        return FAIL, name, 'missing: YQPoint pages and lotteries fail'
    if Organization.objects.filter(oname=org_name).exists():
        return OK, name, f'organization {org_name!r} exists'
    return (production_level(), name, f'no organization named {org_name!r}: '
            'lottery results cannot be announced')
