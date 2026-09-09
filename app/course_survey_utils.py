"""Course prerequisite selection and atomic submission of the user's survey."""
import re

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from app.config import CONFIG
from questionnaire.models import AnswerSheet, AnswerText, Survey
from questionnaire.utils import create_answersheet, lock_draft_answersheet, submit_answersheet

__all__ = ['get_course_prerequisite_survey', 'has_completed_course_survey',
           'submit_course_survey']


def get_course_prerequisite_survey(user):
    """First re.search match wins; disabled/missing configuration requires none.

    Enabled configurations require a fallback and unambiguous survey titles.
    Invalid rules fail closed, including invalid rules after a matching rule.
    """
    config = CONFIG.course.prerequisite_survey
    enabled = config.get('enabled', False)
    if not isinstance(enabled, bool):
        raise ImproperlyConfigured('course.prerequisite_survey.enabled must be boolean')
    if not enabled:
        return None
    rules = config.get('rules', [])
    title = config.get('fallback')
    if not isinstance(rules, list) or not isinstance(title, str) or not title.strip():
        raise ImproperlyConfigured('Course survey requires rules and a fallback title')
    compiled = []
    for rule in rules:
        if (not isinstance(rule, dict) or not isinstance(rule.get('pattern'), str)
                or not isinstance(rule.get('survey'), str) or not rule['survey'].strip()):
            raise ImproperlyConfigured('Invalid course survey rule')
        try:
            compiled.append((re.compile(rule['pattern']), rule['survey']))
        except re.error as exc:
            raise ImproperlyConfigured('Invalid course survey regular expression') from exc
    for pattern, survey_title in compiled:
        if pattern.search(user.username):
            title = survey_title
            break
    try:
        return Survey.objects.get(title=title)
    except (Survey.DoesNotExist, Survey.MultipleObjectsReturned) as exc:
        raise ImproperlyConfigured('Course survey title must identify exactly one survey') from exc


def has_completed_course_survey(user, survey):
    return AnswerSheet.objects.filter(
        creator=user, survey=survey, status=AnswerSheet.Status.SUBMITTED,
    ).exists()


@transaction.atomic
def submit_course_survey(user, survey, answers):
    """Replace a draft's answers and submit via the questionnaire validator.

    Submitted sheets are immutable. Draft replacement and submission roll back
    together on validation errors; all writes are scoped to the current actor.
    """
    sheet = AnswerSheet.objects.filter(creator=user, survey=survey).first()
    if sheet is None:
        sheet = create_answersheet(survey.pk, user)
    sheet = lock_draft_answersheet(sheet.pk, user)
    AnswerText.objects.filter(answersheet=sheet).delete()
    AnswerText.objects.bulk_create([
        AnswerText(answersheet=sheet, question_id=question_id, body=body)
        for question_id, body in answers.items() if body
    ])
    return submit_answersheet(sheet.pk, user)
