"""
excel 上传成就
"""

from django.core.management.base import BaseCommand
import pandas as pd

from achievement.models import Achievement
from achievement.api import bulk_add_achievement_record
from generic.models import User

class Command(BaseCommand):
    """
    从excel中导入成就 格式：学号 成就

    filepath: excel文件路径
    """

    help = "upload achievements from excel"

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str)

    def handle(self, *args, **options):

        # 读取 excel
        filepath = options['filepath']
        full_path = filepath
        data = None
        if filepath.endswith('xlsx') or filepath.endswith('xls'):
            data =  pd.read_excel(f'{full_path}', sheet_name=None)
        elif filepath.endswith('csv'):
            data =  pd.read_csv(f'{full_path}', dtype=object, encoding='utf-8')
        else:
            data = pd.read_table(f'{full_path}', dtype=object, encoding='utf-8')

        if data == None:
            print('文件格式不正确')
            return

        # 默认选取第一个sheet
        if type(data) == dict:
            data = data[list(data.keys())[0]]
        
        data['学号'] = data['学号'].astype(str)

        # 应用api接口分类批量上传成就
        grouped = data.groupby('成就')
        for achievement_name, achievement_data in grouped:
            user_number_list = list(set(achievement_data['学号'].values))
            user_list = User.objects.filter(username__in=user_number_list)
            bulk_add_achievement_record(user_list, Achievement.objects.get(name=achievement_name))
