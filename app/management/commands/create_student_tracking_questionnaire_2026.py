from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from app.student_tracking_survey import create_student_tracking_surveys


class Command(BaseCommand):
    help = '创建 2026 秋元培在校生追踪问卷（普通版 21 题、新生版 11 题）。'

    def add_arguments(self, parser):
        parser.add_argument('--creator', required=True, help='现有创建人账号的 User.username')
        parser.add_argument('--start', required=True, help='本地开始时间，格式 YYYY-MM-DD HH:MM:SS')
        parser.add_argument('--end', required=True, help='本地结束时间，格式 YYYY-MM-DD HH:MM:SS')
        parser.add_argument('--publish', action='store_true', help='将新建问卷设为发布中；默认创建草稿')

    def handle(self, *args, **options):
        try:
            start = datetime.strptime(options['start'], '%Y-%m-%d %H:%M:%S')
            end = datetime.strptime(options['end'], '%Y-%m-%d %H:%M:%S')
        except ValueError as exc:
            raise CommandError('时间格式应为 YYYY-MM-DD HH:MM:SS。') from exc
        try:
            results = create_student_tracking_surveys(
                options['creator'], start, end, publish=options['publish'])
        except ValidationError as exc:
            raise CommandError('；'.join(exc.messages)) from exc
        for title, created in results:
            if created:
                state = '发布中' if options['publish'] else '草稿'
                self.stdout.write(self.style.SUCCESS(f'已创建「{title}」（{state}）。'))
            else:
                self.stdout.write(self.style.WARNING(f'「{title}」已存在，保留原问卷。'))
