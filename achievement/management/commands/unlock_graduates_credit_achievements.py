"""
解锁毕业生 '本科均没有扣除信用分' 成就
"""
from datetime import date, timedelta
import pandas as pd

from django.core.management.base import BaseCommand
from achievement.models import Achievement
from achievement.utils import bulk_add_achievement_record, get_students_without_credit_record


class Command(BaseCommand):
    '''    
    从excel中导入成就 格式：学号

    filepath: excel文件路径

    会自动判断是否有扣分记录
    '''
    help = "解锁毕业生 '本科均没有扣除信用分' 成就"

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
        
        graduate_number = data['学号'].astype(str).tolist()

        # 读取学号
        today = date.today()
        students = get_students_without_credit_record(
            today-timedelta(days=365*6), today).filter(username__in=graduate_number)
        achievement = Achievement.objects.get(name='本科均没有扣除信用分')
        bulk_add_achievement_record(students, achievement)
