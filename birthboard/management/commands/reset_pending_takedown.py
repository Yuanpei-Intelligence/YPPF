"""人工清除投放记录的「等待下架」标记与失败计数。

用于 P0 熔断后的人工恢复：当某条记录连续下架失败达到阈值被停止自动重试，
可先修复外屏/路径问题，再运行本命令重置后由定时任务继续重试。

用法：
    python manage.py reset_pending_takedown 12 13
    python manage.py reset_pending_takedown --all
"""
from django.core.management.base import BaseCommand

from birthboard.models import BirthboardRecord


class Command(BaseCommand):
    help = 'Clear display_takedown_pending / takedown_fail_count for records.'

    def add_arguments(self, parser):
        parser.add_argument('record_ids', nargs='*', type=int,
                            help='要重置的记录 id（可多个）')
        parser.add_argument('--all', action='store_true',
                            help='重置全部带下架标记的记录')

    def handle(self, *args, **options):
        if options['all']:
            qs = BirthboardRecord.objects.all()
        elif options['record_ids']:
            qs = BirthboardRecord.objects.filter(id__in=options['record_ids'])
        else:
            self.stderr.write('请提供记录 id 或 --all。')
            return

        # 只清 pending/计数，不动业务状态与资金，不产生变更记录
        updated = qs.filter(
            display_takedown_pending=True,
        ).update(display_takedown_pending=False, takedown_fail_count=0)
        self.stdout.write(self.style.SUCCESS(
            f'已重置 {updated} 条记录的下架标记与失败计数。'))
