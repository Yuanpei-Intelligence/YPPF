import pandas as pd
from django.core.management.base import BaseCommand
from tqdm import tqdm

from dormitory.models import Dormitory, DormitoryAssignment
from generic.models import User


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
            dormitory = Dormitory.objects.get(id=dorm_id)
            for i in range(len(df)):
                user = User.objects.get(username=df.iloc[i]["学号"])
                bed_id = int(df.iloc[i]["床位"])
                _, created = DormitoryAssignment.objects.get_or_create(
                    dormitory=dormitory,
                    user=user,
                    bed_id=bed_id
                )
                if not created:
                    print(
                        f"This dormitory assignment entity already exists. Info: Dormitory id {dormitory.id}, user {user}, bed id {bed_id}.")