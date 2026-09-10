"""
``timetable_check [--warn-only]``: the deployment readiness checklist of the
timetable feature (``timetable/README.md`` §9) as one line per check —
``[OK]``, ``[WARN]`` or ``[FAIL]`` — followed by a summary. The command
exits non-zero when any check fails unless ``--warn-only`` is given, so it
can gate a deployment or run as a post-deploy smoke step.

Checks: pending migrations of the timetable apps, ``global.base_url``,
``pku_portal.enabled``, the registered ``timetable.sources``, the class
reminder subscribe template, the poster share assets (official-account QR
file present, ``MEDIA_ROOT`` writable), the reminder job module, and for
the current / upcoming term the calendar events, ``exam_week_start``, the
course catalog and the exam schedule.
"""
from __future__ import annotations

import importlib
import os
from datetime import date

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from api.config import get_share_config, get_subscribe_template
from pku_account.config import CONFIG as PORTAL_CONFIG
from semester.calendar import events_between
from timetable.models import AcademicTerm, CourseCatalogEntry, CourseExam
from timetable.sources.base import load_sources
from utils.http.utils import build_full_url

CHECKED_APPS = ('semester', 'pku_account', 'timetable', 'academic_record')
EXPECTED_SOURCES = ('stored', 'college', 'activity', 'appoint', 'exam')
STATIC_PREFIX = '/static/'


class Command(BaseCommand):
    help = ('Check that the timetable feature is configured and seeded for '
            'deployment; exits non-zero on failures unless --warn-only.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--warn-only', action='store_true',
            help='report failures but exit 0')

    def handle(self, *args, **options):
        results: list[tuple[str, str, str]] = []

        def add(level: str, name: str, detail: str = '') -> None:
            results.append((level, name, detail))

        self._check_migrations(add)
        self._check_config(add)
        self._check_jobs(add)
        self._check_terms(add)

        for level, name, detail in results:
            line = f'[{level}] {name}'
            if detail:
                line += f': {detail}'
            self.stdout.write(line)
        fails = [name for level, name, _ in results if level == 'FAIL']
        warns = sum(1 for level, _, _ in results if level == 'WARN')
        self.stdout.write(
            f'{len(results)} checks, {len(fails)} failed, {warns} warning(s)')
        if fails and not options['warn_only']:
            raise CommandError('timetable_check failed: ' + ', '.join(fails))

    # ------------------------------------------------------------------
    def _check_migrations(self, add) -> None:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        pending = [f'{app}.{name}' for (app, name), _ in plan if app in CHECKED_APPS]
        if pending:
            add('FAIL', 'migrations', 'pending: ' + ', '.join(pending))
        else:
            add('OK', 'migrations', 'all applied')

    def _check_config(self, add) -> None:
        base = build_full_url('/')
        if 'localhost' in base or '127.0.0.1' in base:
            add('WARN', 'global.base_url',
                f'{base} (a local host: ICS links and poster assets will not be reachable)')
        else:
            add('OK', 'global.base_url', base)

        if PORTAL_CONFIG.enabled:
            add('OK', 'pku_portal.enabled', 'portal login and import on')
        else:
            add('WARN', 'pku_portal.enabled',
                'false: only paste import and manual entries are available')

        keys = [source.key for source in load_sources()]
        missing = [key for key in EXPECTED_SOURCES if key not in keys]
        if missing:
            add('WARN', 'timetable.sources',
                f'loaded {keys}; missing {missing} (add them to config.json)')
        else:
            add('OK', 'timetable.sources', f'loaded {keys}')

        if get_subscribe_template('class_reminder'):
            add('OK', 'wx_miniapp.subscribe_templates.class_reminder', 'template id set')
        else:
            add('WARN', 'wx_miniapp.subscribe_templates.class_reminder',
                'no template id: reminders fall back to notifications only')

        share = get_share_config()
        qr = share['official_qrcode_url']
        if not qr:
            add('WARN', 'wx_miniapp.share.official_qrcode_url',
                'empty: the poster carries no official-account QR code')
        elif qr.startswith(STATIC_PREFIX):
            if finders.find(qr[len(STATIC_PREFIX):]):
                add('OK', 'wx_miniapp.share.official_qrcode_url', qr)
            else:
                add('FAIL', 'wx_miniapp.share.official_qrcode_url',
                    f'{qr}: static file not found')
        else:
            add('OK', 'wx_miniapp.share.official_qrcode_url', qr)

        media_root = str(settings.MEDIA_ROOT)
        if os.path.isdir(media_root) and os.access(media_root, os.W_OK):
            add('OK', 'MEDIA_ROOT', f'{media_root} writable (mini-program code cache)')
        else:
            add('WARN', 'MEDIA_ROOT',
                f'{media_root} missing or read-only: the mini-program code cannot be cached')

    def _check_jobs(self, add) -> None:
        try:
            importlib.import_module('timetable.jobs')
        except Exception as exc:  # pragma: no cover - import errors are environmental
            add('FAIL', 'timetable.jobs', str(exc))
        else:
            add('OK', 'timetable.jobs',
                'importable (collect_jobs / runscheduler pick up class reminders)')

    def _check_terms(self, add) -> None:
        today = date.today()
        current = AcademicTerm.current(today)
        upcoming = AcademicTerm.upcoming(today)
        if current is None and upcoming is None:
            add('FAIL', 'AcademicTerm',
                'no term: run import_academic_calendar timetable/data/calendar_<code>.json')
            return
        for label, term in (('current', current), ('upcoming', upcoming)):
            if term is None:
                continue
            events = events_between(term.week1_monday, term.end_date())
            catalog = CourseCatalogEntry.objects.filter(term=term).count()
            exams = CourseExam.objects.filter(term=term).count()
            add('OK', f'term ({label})',
                f'{term.code} weeks={term.total_weeks} exam_week_start={term.exam_week_start} '
                f'calendar_events={len(events)} catalog={catalog} exams={exams}')
            if not events:
                add('WARN', f'term {term.code} calendar',
                    'no calendar events: holidays will not suspend classes '
                    '(import_academic_calendar)')
            if term.exam_week_start is None:
                add('WARN', f'term {term.code} exam weeks',
                    'exam_week_start unset: no 考试周 labels')
            if catalog == 0:
                add('WARN', f'term {term.code} catalog',
                    'empty: run import_course_catalog (旁听 and catalog linking need it)')
            if exams == 0:
                add('WARN', f'term {term.code} exams',
                    'empty: run import_exam_schedule once the 教务部 table is published')
