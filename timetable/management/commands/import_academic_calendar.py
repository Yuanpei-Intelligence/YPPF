"""
``import_academic_calendar <file> [--dry-run]``: load one term of the
university calendar (校历) transcribed to JSON (``timetable/README.md``
§6.4 and §8.4, examples in ``timetable/data/``) — upsert the
``AcademicTerm`` named by the file (``code``, ``name``, ``week1_monday``,
``total_weeks``, optional ``exam_week_start``; ``section_times`` and
``is_active`` of an existing term are kept) and
replace the ``semester.CalendarEvent`` rows of that term with the file's
events.

"Rows of the term" are those overlapping the window from the term's week 1
(or the file's earliest event, if earlier) to the Sunday of its last
teaching week (or the file's latest event, if later — the exam period and
the vacation after a term belong to that term's file). Rows outside the
window are untouched, so the fall and spring files can be imported in any
order and re-imported at will: running the command twice yields the same
rows. Everything happens in one transaction; an invalid file writes nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from timetable.calendar import (
    CalendarEventSpec,
    CalendarImportResult,
    CalendarSpec,
    CalendarSpecError,
    apply_calendar_spec,
    parse_calendar_spec,
)


class Command(BaseCommand):
    help = ('Import one term of the university calendar (校历) from a JSON file: '
            'upsert the AcademicTerm and replace the CalendarEvent rows of its '
            'date range (see timetable/README.md §6.4).')

    def add_arguments(self, parser):
        parser.add_argument(
            'file', help='JSON file (format: timetable/README.md §6.4; '
                         'examples: timetable/data/calendar_*.json)')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='validate the file and print what would change without writing')

    def handle(self, *args, **options):
        path = Path(options['file'])
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except OSError as exc:
            raise CommandError(f'cannot read {path}: {exc}')
        except ValueError as exc:
            raise CommandError(f'{path}: not valid JSON: {exc}')
        try:
            spec = parse_calendar_spec(data)
        except CalendarSpecError as exc:
            raise CommandError(f'{path}: invalid calendar:\n  - '
                               + '\n  - '.join(exc.problems))
        result = apply_calendar_spec(spec, dry_run=options['dry_run'])
        self._report(result)

    def _report(self, result: CalendarImportResult) -> None:
        spec = result.spec
        if result.term_created:
            state = 'new term'
        elif result.term_changes:
            state = 'existing term, ' + ', '.join(
                f'{name} {old} -> {new}'
                for name, (old, new) in result.term_changes.items())
        else:
            state = 'existing term, unchanged'
        exam_weeks = ''
        if spec.exam_week_start is not None:
            exam_weeks = f', exam weeks from week {spec.exam_week_start}'
        self.stdout.write(f'{spec.code} {spec.name}: week 1 from {spec.week1_monday}, '
                          f'{spec.total_weeks} week(s){exam_weeks} ({state})')
        for event in spec.events:
            self.stdout.write(f'  {event.kind:<8} {event.start} .. {event.end}  '
                              f'{_weeks_label(spec, event):<12} {event.name}')
        window = f'{result.window[0]} .. {result.window[1]}'
        if result.dry_run:
            self.stdout.write(self.style.WARNING(
                f'dry run: would replace {result.removed} event(s) in {window} '
                f'with {result.written}; nothing written'))
            return
        verb = ('created' if result.term_created
                else 'updated' if result.term_changes else 'kept')
        self.stdout.write(self.style.SUCCESS(
            f'done: {verb} term {spec.code}, replaced {result.removed} event(s) '
            f'in {window} with {result.written}'))


def _weeks_label(spec: CalendarSpec, event: CalendarEventSpec) -> str:
    first, last = spec.week_of(event.start), spec.week_of(event.end)
    return f'week {first}' if first == last else f'weeks {first}-{last}'
