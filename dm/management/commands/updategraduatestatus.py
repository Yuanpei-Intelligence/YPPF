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
    1: '已毕业',
    2: '住宿辅导员',
    3: '延毕',
    4: '休学',
}

def _load_from_csv(file_path):
    """从csv文件加载学号和状态"""
    if not os.path.exists(file_path):
        raise CommandError('指定的文件路径不存在: %s' % file_path)
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            #if len(row) != 2:
                #raise CommandError('文件格式错误,每行应包含学号和状态两列,用逗号分隔: %s' % ','.join(row))
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
    help = '通过文件批量修改学生的毕业情况状态（毕业、休学、延毕、住宿辅导员）'

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            '--config',
            type=str,
            help='指定包含特殊处理名单的csv文件路径,每行学号和状态(0-在读,1-已毕业,2-住宿辅导员,3-延毕,4-休学)用逗号分隔',
            required=True
        )


    def handle(self, *args, **options):
        config = options['config']

        data = _load_from_csv(config)
        # Test run
        cnt_modify = 0
        cnt_nochange = 0
        cnt_notfound = 0
        for stu_id, status in data:
            try:
                person = NaturalPerson.objects.get(
                    stu_id_dbonly=stu_id,
                    identity = NaturalPerson.Identity.STUDENT)
            except NaturalPerson.DoesNotExist:
                self.stdout.write(self.style.ERROR('学号%s的学生不存在,跳过' % stu_id))
                cnt_notfound += 1
                continue
            old_status = status_map[person.status]
            new_status = status_map[status]
            
            if old_status != new_status:
                cnt_modify += 1
                self.stdout.write(self.style.SUCCESS('学号%s的学生状态: %s -> %s' % (stu_id, old_status, new_status)))
            else:
                cnt_nochange += 1
                self.stdout.write(self.style.SUCCESS('学号%s的学生状态: %s 不变' % (stu_id, old_status)))

        self.stdout.write(self.style.WARNING('=> 共处理学生%d人, 修改状态%d人, 未修改%d人, 未找到%d人' % (
            cnt_modify + cnt_nochange + cnt_notfound, cnt_modify, cnt_nochange, cnt_notfound)))
        self.stdout.write(self.style.WARNING('请确认无误后,输入y以继续,n以取消'))

        confirm = input()
        if confirm.lower() != 'y':
            self.stdout.write(self.style.ERROR('操作已取消'))
            return
        else:
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
                    if status == NaturalPerson.GraduateStatus.GRADUATED or status == NaturalPerson.GraduateStatus.ONLEAVE:
                        person.person_id.active = False # 毕业和休学的账号也要设置
                        person.accept_promote = False
                        person.person_id.save()
                    else:
                        person.person_id.active = True
                        person.accept_promote = True
                        person.person_id.save()
                    person.save()
                    self.stdout.write(self.style.SUCCESS('成功将学号%s的学生状态调整为%s' % (stu_id, status_map[status])))
