"""
Deployment checks of the timetable app (``timetable/README.md`` §9), run by
``python manage.py deploy_check`` together with every other app's checks.

Project-wide items (migrations, ``global.base_url``, ``MEDIA_ROOT``, the
scheduler) belong to the core checks; this module covers what only the
timetable needs: its registered sources, the class-reminder subscribe
template, the poster share assets, the reminder job module and, for the
current and upcoming term, the calendar, exam weeks, course catalog and exam
schedule. With ``online=True`` it also asks WeChat for the mini-program code
used on the poster.
"""
from __future__ import annotations

import importlib
from datetime import date
from typing import Iterator

from django.contrib.staticfiles import finders

from api.config import get_share_config, get_subscribe_template
from semester.calendar import events_between
from timetable.models import AcademicTerm, CourseCatalogEntry, CourseExam
from timetable.sources.base import load_sources

__all__ = ['checks', 'EXPECTED_SOURCES']

EXPECTED_SOURCES = ('stored', 'college', 'activity', 'appoint', 'exam')
STATIC_PREFIX = '/static/'


def checks(*, online: bool = False) -> Iterator[tuple[str, str, str]]:
    """Yield ``(level, name, detail)`` with level ``'OK'``, ``'WARN'`` or ``'FAIL'``."""
    yield from _config_checks()
    yield _jobs_check()
    yield from _term_checks(date.today())
    if online:
        yield _miniapp_code_check()


def _config_checks() -> Iterator[tuple[str, str, str]]:
    keys = [source.key for source in load_sources()]
    missing = [key for key in EXPECTED_SOURCES if key not in keys]
    if missing:
        yield ('WARN', 'timetable.sources',
               f'loaded {keys}; missing {missing} (add them to config.json)')
    else:
        yield ('OK', 'timetable.sources', f'loaded {keys}')

    if get_subscribe_template('class_reminder'):
        yield ('OK', 'wx_miniapp.subscribe_templates.class_reminder', 'template id set')
    else:
        yield ('WARN', 'wx_miniapp.subscribe_templates.class_reminder',
               'no template id: class reminders fall back to notifications only')

    qr = get_share_config()['official_qrcode_url']
    if not qr:
        yield ('WARN', 'wx_miniapp.share.official_qrcode_url',
               'empty: the poster carries no official-account QR code')
    elif qr.startswith(STATIC_PREFIX) and not finders.find(qr[len(STATIC_PREFIX):]):
        yield ('FAIL', 'wx_miniapp.share.official_qrcode_url', f'{qr}: static file not found')
    else:
        yield ('OK', 'wx_miniapp.share.official_qrcode_url', qr)


def _jobs_check() -> tuple[str, str, str]:
    try:
        importlib.import_module('timetable.jobs')
    except Exception as exc:  # an import error is environmental; report its class only
        return ('FAIL', 'timetable.jobs', f'import failed ({exc.__class__.__name__})')
    return ('OK', 'timetable.jobs',
            'importable (collect_jobs / runscheduler send class reminders)')


def _term_checks(today: date) -> Iterator[tuple[str, str, str]]:
    current = AcademicTerm.current(today)
    upcoming = AcademicTerm.upcoming(today)
    if current is None and upcoming is None:
        yield ('FAIL', 'AcademicTerm',
               'no term: run import_academic_calendar timetable/data/calendar_<code>.json')
        return
    for label, term in (('current', current), ('upcoming', upcoming)):
        if term is None:
            continue
        events = events_between(term.week1_monday, term.end_date())
        catalog = CourseCatalogEntry.objects.filter(term=term).count()
        exams = CourseExam.objects.filter(term=term).count()
        yield ('OK', f'term ({label})',
               f'{term.code} weeks={term.total_weeks} exam_week_start={term.exam_week_start} '
               f'calendar_events={len(events)} catalog={catalog} exams={exams}')
        if not events:
            yield ('WARN', f'term {term.code} calendar',
                   'no calendar events: holidays will not suspend classes '
                   '(import_academic_calendar)')
        if term.exam_week_start is None:
            yield ('WARN', f'term {term.code} exam weeks',
                   'exam_week_start unset: no 考试周 labels')
        if catalog == 0:
            yield ('WARN', f'term {term.code} catalog',
                   'empty: run import_course_catalog (旁听 and catalog linking need it)')
        if exams == 0:
            yield ('WARN', f'term {term.code} exams',
                   'empty: run import_exam_schedule once the 教务部 table is published')


def _miniapp_code_check() -> tuple[str, str, str]:
    from timetable.share import miniapp_code_url

    if miniapp_code_url():
        return ('OK', 'poster mini-program code', 'produced (or served from the 30-day cache)')
    return ('WARN', 'poster mini-program code',
            'WeChat did not return a code: check wx_miniapp appid/secret, share.env_version '
            'and that share.miniapp_page is published')
