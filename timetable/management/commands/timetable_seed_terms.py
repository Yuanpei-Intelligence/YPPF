"""
``python manage.py timetable_seed_terms`` — create ``AcademicTerm`` rows from
``semester.Semester``. Idempotent: existing codes are left untouched.
Contract: ``timetable/README.md`` §4.1.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from semester.models import Semester
from timetable.models import AcademicTerm


def term_suffix(type_name: str) -> int | None:
    """Portal term suffix of a YPPF semester type name: 秋 → 1, 春 → 2, 夏 → 3."""
    if '秋' in type_name:
        return 1
    if '春' in type_name:
        return 2
    if '夏' in type_name:
        return 3
    return None


_SUFFIX_NAMES = {1: '秋季', 2: '春季', 3: '夏季'}


class Command(BaseCommand):
    help = ('Create timetable AcademicTerm rows from semester.Semester '
            '(start_date aligned to Monday → week1_monday; 秋/春 → code '
            'suffix 1/2). Existing terms are never modified.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--total-weeks', type=int, default=16,
            help='total_weeks of newly created terms (default 16)')

    def handle(self, *args, **options):
        total_weeks = options['total_weeks']
        created = existing = skipped = 0
        semesters = Semester.objects.select_related('type').order_by('start_date')
        for semester in semesters:
            suffix = term_suffix(semester.type.name)
            if suffix is None:
                skipped += 1
                self.stdout.write(
                    f'skip {semester.year} {semester.type.name}: unknown type')
                continue
            year = semester.year
            code = f'{year % 100:02d}-{(year + 1) % 100:02d}-{suffix}'
            week1_monday = semester.start_date - timedelta(
                days=semester.start_date.weekday())
            name = f'{year}-{year + 1}学年{_SUFFIX_NAMES[suffix]}学期'
            term, was_created = AcademicTerm.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'week1_monday': week1_monday,
                    'total_weeks': total_weeks,
                })
            if was_created:
                created += 1
                self.stdout.write(f'created {code}: {name}, week 1 from {week1_monday}')
            else:
                existing += 1
                self.stdout.write(f'exists {code}: {term.name}')
        self.stdout.write(self.style.SUCCESS(
            f'done: created {created}, existing {existing}, skipped {skipped}'))
