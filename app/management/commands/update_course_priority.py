from django.core.management.base import BaseCommand

from app.models import NaturalPerson, CourseRecord
from semester.api import semester_of
from datetime import datetime, timedelta

class Command(BaseCommand):
    # This command should be run before new semester starts
    help = "Updates course_priority for all NaturalPerson"

    def handle(self, *args, **options):
        # Currently, just adjust all of them to 1.
        NaturalPerson.objects.update(course_priority=1.0)
        # Comment out this return to enable course priority
        return
        # Gets the semester three months ago
        sem = semester_of(datetime.now() - timedelta(days=90))
        # A list of invalid record's student id.
        # FIXME: This is too ugly. Try reformat after issue #869 is resolved
        invalid_id = CourseRecord.objects.filter(
            year=sem.year, invalid=True,
            semester='Fall' if '秋' in sem.type.name else 'Spring'
        ).values_list('person__id', flat = True)
        # Number of times appearing in the invalid list
        invalid_cnt = dict()
        for i in invalid_id:
            if i not in invalid_cnt.keys():
                invalid_cnt[i] = 0
            invalid_cnt[i] += 1
        for person_id in invalid_cnt:
            p = max(0.5, 1 - 0.05 * invalid_cnt[person_id])
            NaturalPerson.objects.filter(id=person_id).update(course_priority=p)
