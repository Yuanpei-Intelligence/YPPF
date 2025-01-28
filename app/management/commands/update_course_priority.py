from django.core.management.base import BaseCommand

from app.course_utils import update_course_priority

class Command(BaseCommand):
    # This command should be run before new semester starts
    help = "Updates course_priority for all NaturalPerson"

    def add_arguments(self, parser):
        parser.add_argument('year', type=int, help='year of the course records to check (required)')
        parser.add_argument('semester', type=str, help='semester of the course records to check. Valid values are: Fall, Spring (required)')

    def handle(self, *args, **options):
        try:
            # 修改这里的这个lambda，可以实现不同的权重策略
            update_course_priority(options['year'], options['semester'],
                                   lambda x: 1 - 0.05 * x)
        except Exception as e:
            print('Error:', e.args)
        else:
            print('Success!')
