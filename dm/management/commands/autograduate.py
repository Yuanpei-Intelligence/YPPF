from django.core.management.base import BaseCommand, CommandParser, CommandError
from django.db import transaction

from app.models import (
    NaturalPerson
)

class Command(BaseCommand):
    help = '通过学号检定批量调整指定年级的学生状态为“已毕业”，延迟毕业的学生需通过管理站点手动再次调整回来'

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            '--year',
            type=int,
            help='指定年级,以两位方式填写(例如20)'
        )

    def handle(self, *args, **options):
        year = options['year']
        
        # 检查参数是否为空
        if year is None:
            raise CommandError('请指定年级参数')
        # 检查年份是否合法
        if year < 15 or year > 29:
            raise CommandError('年级参数不合法')
        
        with transaction.atomic():
            # 选出指定年级的学生(通过学号前两位判断,person_id为学号)
            students = NaturalPerson.objects.filter(person_id__username__startswith=str(year))
            for student in students:
                student.status = NaturalPerson.GraduateStatus.GRADUATED
                student.save()
            # 打印结果
            self.stdout.write(self.style.SUCCESS('成功将%d级学生状态调整为“已毕业”' % year))
                