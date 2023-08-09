from django.core.management.base import BaseCommand
from generic.models import User


class Command(BaseCommand):
    help = "Assign dormitory."

    def handle(self, *args, **options):
        # 筛选出新生
        students = User.objects.filter(utype=User.Type.STUDENT) # 还需要加一个年级的筛选
        