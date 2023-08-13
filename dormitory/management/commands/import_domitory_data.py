from django.core.management.base import BaseCommand
from dormitory.models import Dormitory
import pandas as pd

# 导入宿舍信息，包括宿舍号、容量（4）、性别。
class Command(BaseCommand):
    help = 'Imports dormitory data'

    def add_arguments(self, parser):
        parser.add_argument('excel_file', type=str, help='Path to the Excel file')

    def handle(self, *args, **options):
        excel_file = options['excel_file']

        try:
            df_raw = pd.read_excel(excel_file)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error reading Excel file: {e}'))
            return
        
        df_dorms = df_raw.groupby('宿舍号')
        for dorm_id, df in df_dorms:
            gender = pd.unique(df['性别'])
            assert len(gender) == 1, len(gender)
            dorm, created = Dormitory.objects.get_or_create(
                id=dorm_id,
                capacity=4,
                gender=gender[0]
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created dorm: {dorm_id}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Dorm already exist: {dorm_id}'))







