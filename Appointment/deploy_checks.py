"""
Room reservation checks of ``python manage.py deploy_check``: the
``underground`` display token and semester start. No I/O. Level policy:
``utils.deploy_check``.
"""
from datetime import date, datetime
from typing import Iterator

from utils.deploy_check import (
    FAIL, OK, is_placeholder, production_level, resolve_setting,
)
from Appointment.config import appointment_config as CONFIG


__all__ = ['checks']


Result = tuple[str, str, str]

# Longer than any term: an older start makes "this semester" span past terms.
MAX_SEMESTER_START_AGE_DAYS = 190


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the ``underground`` configuration checks."""
    yield _check_display_token()
    yield _check_semester_start(date.today())


def _check_display_token() -> Result:
    name = 'underground.token.display'
    token, error = resolve_setting(CONFIG, 'display_token')
    # display_getappoint compares the request's token with this value, so an
    # unset or empty value also admits requests without a real token.
    if error or token is None or (isinstance(token, str) and not token.strip()):
        return (production_level(), name, 'unset or empty: the room display API '
                'serves appointments without a real token')
    if not isinstance(token, str):
        return FAIL, name, 'not a string: room displays are always rejected'
    if is_placeholder(token):
        return (production_level(), name, 'the template placeholder: the room '
                'display token is public')
    return OK, name, 'set'


def _check_semester_start(today: date) -> Result:
    name = 'underground.semester_data.semester_start'
    start, error = resolve_setting(CONFIG, 'semester_start')
    if error or not isinstance(start, datetime):
        return (FAIL, name, 'missing or not a date: violation and long-term '
                'appointment pages fail')
    age = (today - start.date()).days
    if age > MAX_SEMESTER_START_AGE_DAYS:
        return (production_level(), name, f'{start:%Y-%m-%d} is {age} days ago: '
                'violations and long-term appointment quotas count past terms')
    return OK, name, f'{start:%Y-%m-%d}'
