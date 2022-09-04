from django.core.management.base import BaseCommand
from app.models import NaturalPerson
from data_analysis.summary import cal_co_appoint, cal_appoint

class Command(BaseCommand):
    help = '导入测试数据'

    def handle(self, *args, **option):
        cur_year = 2022
        co_list, func_list, discuss_list = [], [], []
        for person in NaturalPerson.objects.activated().exclude(stu_grade=cur_year):
            sid = person.person_id.username
            co_list.append((sid, cal_co_appoint(person).get('co_appoint_hour', 0)))
            appoint_info = cal_appoint(person)
            discuss_list.append((sid, appoint_info.get('discuss_appoint_hour', 0)))
            func_list.append((sid, appoint_info.get('func_appoint_hour', 0)))
        co_list = sorted(co_list, key=lambda x: x[1])
        func_list = sorted(func_list, key=lambda x: x[1])
        discuss_list = sorted(discuss_list, key=lambda x: x[1])
        return dict(
            co_pct = [s for s, _ in co_list],
            func_appoint_pct = [s for s, _ in func_list],
            discuss_list = [s for s, _ in discuss_list]
        )