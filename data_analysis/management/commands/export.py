import os
from datetime import datetime

from django.core.management.base import BaseCommand
from django.conf import settings

from boottest.hasher import MySHA256Hasher
from app.constants import CURRENT_ACADEMIC_YEAR
from data_analysis.management import dump_map


def valid_datetime(s: str) -> datetime:
    """Generate valid datetime from str

    :param s: time str
    :type s: str
    :raises ValueError: Unexpected time format
    :return: datetime
    :rtype: datetime
    """
    try:
        return datetime.strptime(s, '%Y-%m-%d')
    except:
        pass
    try:
        return datetime.strptime(s, '%Y-%m-%d-%H:%M')
    except:
        pass
    msg = '日期格式错误："{0}"，格式："YY-mm-dd-HH:MM"或"YY-mm-dd"'.format(s)
    raise ValueError(msg)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('task', type=str, nargs='+',
                            help='Specify dumping task. Use all to execute all.',
                            choices=['all'] + list(dump_map.keys()))
        parser.add_argument('-d', '--directory', type=str, help='Dumping directory.',
                            default=os.path.join(settings.MY_TMP_DIR, str(datetime.now().date)))
        parser.add_argument('-s', '--start-time', type=valid_datetime,
                            default=None, help='Start time. Format: YY-mm-dd-HH:MM or YY-mm-dd')
        parser.add_argument('-e', '--end-time', type=valid_datetime,
                            default=None, help='End time. Format: YY-mm-dd-HH:MM or YY-mm-dd')
        parser.add_argument('-y', '--year', type=int,
                            help='Academic Year', default=CURRENT_ACADEMIC_YEAR)
        parser.add_argument('-m', '--mask', type=bool,
                            default=True, help='Mask student id.')
        parser.add_argument('-S', '--salt', type=str,
                            default=str(os.urandom(8)), help='hash salt')
        parser.add_argument('--semester', type=str, help='Semester',
                            choices=['Fall', 'Spring', 'Fall+Spring'], default='Fall+Spring')

    def handle(self, *args, **options):
        hash_func = MySHA256Hasher(
            options['salt']).encode if options['mask'] else None

        tasks = options['task']
        if 'all' in options['task']:
            tasks = dump_map.keys()
        for task in tasks:
            for dump_function, default_filename, accept_params in dump_map[task]:
                data_frame = dump_function(
                    hash_func=hash_func, **options.fromkeys(accept_params))
                data_frame.to_csv(os.path.join(
                    options['directory'], f'{default_filename}.csv'), index=False)
