from django.core.management.base import BaseCommand
from django.db import transaction

from app.models import NaturalPerson, CourseRecord

from typing import Dict, List
from tqdm import trange

class Command(BaseCommand):
    # This command should be run before new semester starts
    help = "Updates course_priority for all NaturalPerson"

    def add_arguments(self, parser):
        parser.add_argument('year', type=int, help='year of the course records to check (required)')
        parser.add_argument('semester', type=str, help='semester of the course records to check. Valid values are: Fall, Spring (required)')

    @transaction.atomic
    def handle(self, *args, **options):
        # Currently, just adjust all of them to 1.
        NaturalPerson.objects.update(course_priority=1.0)
        # Comment out this return to enable course priority
        # return
        if options['semester'] not in ('Fall', 'Spring'):
            print('Error: <semester> must have value of "Fall" or "Spring"!')
            return
        # A list of invalid record's student id.
        invalid_id: List[int] = list(CourseRecord.objects.filter(
            year = options['year'], invalid = True, semester = options['semester']
        ).order_by(
            'person__id'
        ).values_list(
            'person__id', flat = True
        ))
        # Number of invalid records
        n = len(invalid_id)
        print(f'update_course_priority: There are {n} invalid records.')
        # a[k] is the list of id of people who have k invalid records
        a: Dict[int, List[int]] = dict()
        # Length of the current continuous segment
        k = 0
        for i in trange(n, desc = 'Processing invalid records'):
            k += 1
            if i == n - 1 or invalid_id[i] != invalid_id[i + 1]:
                if k not in a:
                    a[k] = []
                a[k].append(invalid_id[i])
                k = 0
        # Print out a summary of invalid records
        for i in a:
            print(f'There are {len(a[i])} people with {i} invalid records...')
            p = max(0.5, 1 - 0.05 * i)
            NaturalPerson.objects.filter(id__in = a[i]).update(course_priority = p)
        print('Done!')