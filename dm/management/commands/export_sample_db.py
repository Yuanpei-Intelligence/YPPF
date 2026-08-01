'''
Export an anonymized ~10% sample of the current database as INSERT-only SQL.
'''

from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from boot.config import BASE_DIR
from dm.sample_db_export import export_sample_database


class Command(BaseCommand):
    help = (
        '对当前数据库按用户主轴采样并脱敏，导出 INSERT-only SQL '
        '（默认约 10%，固定 seed；更新仓库样例时请覆盖根目录 dev_sample.sql）'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--ratio',
            type=float,
            default=0.1,
            help='用户采样比例，默认 0.1',
        )
        parser.add_argument(
            '--seed',
            type=int,
            default=42,
            help='随机种子，默认 42',
        )
        parser.add_argument(
            '--outdir',
            type=str,
            default='raw_data',
            help='输出目录（相对项目根或绝对路径），默认 raw_data',
        )

    def handle(self, *args, **options):
        ratio = options['ratio']
        seed = options['seed']
        outdir = Path(options['outdir'])
        if not outdir.is_absolute():
            outdir = Path(BASE_DIR) / outdir

        if not 0 < ratio <= 1:
            raise CommandError('--ratio 必须在 (0, 1] 内')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        outfile = outdir / f'dev_sample_{timestamp}.sql'

        self.stdout.write(
            f'Exporting anonymized sample to {outfile} '
            f'(ratio={ratio}, seed={seed}) ...'
        )
        summary = export_sample_database(
            outfile, ratio=ratio, seed=seed
        )
        self.stdout.write(self.style.SUCCESS(
            f'Done: users={summary["users"]} path={summary["path"]}'
        ))
        self.stdout.write(
            'Import reminder: empty DB -> migrate -> '
            'python scripts/import_dev_sample.py'
        )
        self.stdout.write(
            'To refresh the committed sample, copy this file to '
            'repository-root dev_sample.sql'
        )
