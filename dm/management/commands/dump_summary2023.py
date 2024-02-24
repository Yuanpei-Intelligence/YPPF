import json

from django.core.management.base import BaseCommand
from dm.summary2023 import *
from datetime import datetime, time, date


def datetime_converter(o):
    if isinstance(o, datetime) | isinstance(o, time) | isinstance(o, date):
        return o.isoformat()


class Command(BaseCommand):
    help = '导出2023年度总结数据'

    def handle(self, *args, **option):

        # 导出汇总信息
        overall_info = generic_info()
        with open('test_data/summary_overall_2023.json', 'w', encoding='utf-8') as f:
            json.dump(overall_info, f, default=datetime_converter,
                      ensure_ascii=False)

        # 导出个人信息
        summary_info = person_infos()
        with open('test_data/summary2023.json', 'w', encoding='utf-8') as f:
            json.dump(summary_info, f, default=datetime_converter,
                      ensure_ascii=False)
