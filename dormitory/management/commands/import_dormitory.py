import pandas as pd
from django.core.management.base import BaseCommand
from tqdm import tqdm

from dormitory.models import Dormitory


# 导入宿舍信息，包括宿舍号、容量（4）、性别。
class Command(BaseCommand):
    help = 'Imports dormitory data'

    def add_arguments(self, parser):
        parser.add_argument('excel_file', type=str,
                            help='Path to the Excel file')

    def handle(self, *args, **options):
        excel_file = options['excel_file']

        try:
            df_raw = pd.read_excel(excel_file)
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'Error reading Excel file: {e}'))
            return

        df_dorms = df_raw.groupby('宿舍号')
        for dorm_id, df in tqdm(df_dorms):

            gender = pd.unique(df['性别'])
            assert len(gender) == 1, len(gender)

            _, created = Dormitory.objects.get_or_create(
                id=dorm_id,
                capacity=4,
                gender={"男": 0, "女": 1}[gender[0]]
            )
            if not created:
                gender_dict = {'男': 'male', '女': 'female'}
                print(
                    f"Dormitory {dorm_id} already exists. Its capacity is 4 and it's a {gender_dict[gender[0]]} dormitory")