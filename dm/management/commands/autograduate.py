from django.core.management.base import BaseCommand, CommandParser, CommandError
from django.db import transaction

from app.models import (
    NaturalPerson,
    User
)
import csv
import os

status_map = {
    0: '在读',
    1: '住宿辅导员',
    2: '延毕',
    3: '休学',
    4: '已毕业'
}

def _load_from_csv(file_path):
    """从csv文件加载学号和状态"""
    if not os.path.exists(file_path):
        raise CommandError('指定的文件路径不存在: %s' % file_path)
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) != 2:
                raise CommandError('文件格式错误,每行应包含学号和状态两列,用逗号分隔: %s' % ','.join(row))
            stu_id = row[0].strip()
            try:
                status = int(row[1].strip())
                if status not in status_map:
                    raise ValueError
            except ValueError:
                raise CommandError('状态值错误,应为 %s: %s' % str(status_map), row[1])
            records.append((stu_id, status))
    return records

class Command(BaseCommand):
    help = '通过学号批量调整指定年级的学生状态为“已毕业”，或通过文件指定特殊处理的学生名单（休学、延毕、住宿辅导员）'

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            '--year',
            type=int,
            help='指定年级,以两位方式填写(例如20)',
            required=False
        )
        parser.add_argument(
            '--config',
            type=str,
            help='指定包含特殊处理名单的csv文件路径,每行学号和状态(0-在读,1-住宿辅导员,2-延毕,3-休学,4-毕业)用逗号分隔',
            required=False
        )

    def handle(self, *args, **options):
        year = options['year']
        config = options['config']
        
        # 检查参数是否为空
        if year is None and config is None:
            raise CommandError('请至少提供一个参数: --year 或 --config')

        # 指定年级
        if year is not None:
            with transaction.atomic():
                # 选出指定年级的自然人(通过学号前两位判断,person_id为学号)
                NaturalPerson.objects.filter(
                    person_id__username__startswith=str(year),
                    identity = NaturalPerson.Identity.STUDENT).update(
                        status = NaturalPerson.GraduateStatus.GRADUATED,
                        accept_promote = False)
                User.objects.filter(
                    username__startswith=str(year),
                    utype = User.Type.STUDENT).update(active = False)
                # 打印结果
                self.stdout.write(self.style.SUCCESS('成功将%d级学生状态调整为“已毕业”' % year))

        # 指定文件
        if config is not None:
            data = _load_from_csv(config)
            with transaction.atomic():
                for stu_id, status in data:
                    try:
                        person = NaturalPerson.objects.get(
                            stu_id_dbonly=stu_id,
                            identity = NaturalPerson.Identity.STUDENT)
                    except NaturalPerson.DoesNotExist:
                        self.stdout.write(self.style.ERROR('学号%s的学生不存在,跳过' % stu_id))
                        continue
                    person.status = status
                    if status == NaturalPerson.GraduateStatus.GRADUATED:
                        person.person_id.active = False # 毕业的账号也要设置
                        person.accept_promote = False
                        person.person_id.save()
                    person.save()
                    self.stdout.write(self.style.SUCCESS('成功将学号%s的学生状态调整为%s' % (stu_id, status_map[status])))
