from django.core.management.base import BaseCommand, CommandParser, CommandError
from django.db import transaction

from app.models import (
    NaturalPerson,
    User
)

status_map = {
    0: '在读',
    1: '住宿辅导员',
    2: '延毕',
    3: '休学',
    4: '已毕业'
}

class Command(BaseCommand):
    help = '通过学号批量调整指定年级的学生状态为“已毕业”'

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            '--year',
            type=int,
            help='指定年级,以两位方式填写(例如20)',
            required=True
        )

    def handle(self, *args, **options):
        year = options['year']
        cnt = 0
        cnt_map = {k:0 for k in status_map.keys()}
        for person in NaturalPerson.objects.filter(person_id__username__startswith=str(year), identity = NaturalPerson.Identity.STUDENT):
            cnt_map[person.status] += 1
            self.stdout.write(self.style.WARNING('学号%s的学生状态: %s => 已毕业' % (person.person_id.username, status_map[person.status])))
            cnt += 1
        
        self.stdout.write(self.style.WARNING('=> 共处理学生%d人' % cnt))
        detail_str = "将要将"
        for k, v in cnt_map.items():
            if v > 0:
                detail_str += " %s %d人," % (status_map[k], v)
        detail_str = detail_str.rstrip(',') + '的状态调整为“已毕业”'
        self.stdout.write(self.style.WARNING(detail_str))
        self.stdout.write(self.style.WARNING('如需保留某些学生，请稍后再用updategraduatestatus命令调整其状态'))
        self.stdout.write(self.style.WARNING('请确认无误后,输入y以继续,n以取消'))
        confirm = input()
        if confirm.lower() != 'y':
            self.stdout.write(self.style.ERROR('操作已取消'))
            return

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
