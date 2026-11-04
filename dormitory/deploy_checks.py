"""
Dormitory checks of ``python manage.py deploy_check``: the routine QA page
looks its survey up by ``dormitory.routine_qa_survey_title``. Level policy:
``utils.deploy_check``.
"""
from typing import Iterator

from utils.deploy_check import OK, WARN, is_blank, resolve_setting
from utils.health_check import db_connection_healthy
from questionnaire.models import Survey
from dormitory.config import dormitory_config as CONFIG


__all__ = ['checks']


Result = tuple[str, str, str]


def checks(*, online: bool = False) -> Iterator[Result]:
    """Yield the routine QA survey check."""
    yield _check_routine_qa_survey(db_connection_healthy())


def _check_routine_qa_survey(database_ok: bool) -> Result:
    # WARN only: the page is a seasonal freshman survey, not a core flow.
    name = 'dormitory.routine_qa_survey_title'
    title, error = resolve_setting(CONFIG, 'routine_qa_survey_title')
    if error or is_blank(title):
        return WARN, name, 'missing: the routine QA page fails'
    if not database_ok:
        return WARN, name, 'skipped: database unreachable'
    count = Survey.objects.filter(title=title).count()
    if count == 1:
        return OK, name, 'the survey exists'
    return (WARN, name, f'{count} surveys titled {title!r}: the routine QA page '
            'fails until exactly one exists')
