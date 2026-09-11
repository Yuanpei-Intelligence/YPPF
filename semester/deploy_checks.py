"""
Semester checks of ``python manage.py deploy_check``.

The homepage and several jobs call ``semester.api.current_semester()``, which
raises when no semester has started, and the 1 September new-school-year job
needs an upcoming semester. Level policy: ``utils.deploy_check``.
"""
from datetime import date
from typing import Iterator

from utils.deploy_check import OK, WARN, production_level
from utils.health_check import db_connection_healthy
from semester.models import Semester


__all__ = ['checks']


Result = tuple[str, str, str]


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the semester table check."""
    if not db_connection_healthy():
        yield WARN, 'semesters', 'skipped: database unreachable'
        return
    yield _check_semesters(date.today())


def _check_semesters(today: date) -> Result:
    name = 'semesters'
    semesters = Semester.objects.select_related('type')
    current = semesters.filter(
        start_date__lte=today, end_date__gte=today).order_by('-start_date').first()
    if current is not None:
        return OK, name, f'{_describe(current)} covers today'
    if not semesters.filter(start_date__lte=today).exists():
        return (production_level(), name, 'no semester has started: the homepage '
                'fails (semester.api.current_semester)')
    upcoming = semesters.filter(start_date__gt=today).order_by('start_date').first()
    if upcoming is None:
        return (WARN, name, 'none covers today and none is upcoming: add the next '
                'semester (the new-school-year job needs it)')
    return (OK, name, f'between semesters; {_describe(upcoming)} starts '
            f'{upcoming.start_date:%Y-%m-%d}')


def _describe(semester: Semester) -> str:
    return f'{semester.year} {semester.type.name}'
