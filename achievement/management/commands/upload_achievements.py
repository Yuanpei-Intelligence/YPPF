"""
excel 上传成就
"""

from django.core.management.base import BaseCommand
import pandas as pd

from achievement.models import AchievementType, Achievement, AchievementUnlock
from generic.models import User


class Command(BaseCommand):
    help = "upload achievements from excel"

    """
    从excel中导入成就 格式：学号 成就

    filepath: excel文件路径
    """

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
        
        # 逐行创建AchievementUnlock 每行数据包括 学号 成就
        for index, row in data.iterrows():
            user_number = row['学号']
            achievement_name = row['成就']
            try:
                user = User.objects.get(username=user_number) # username就是学号
                achievement = Achievement.objects.get(name=achievement_name)
                AchievementUnlock.objects.create(user=user, achievement=achievement)
            except:
                print(f'学号{user_number}或成就{achievement_name}不存在')
