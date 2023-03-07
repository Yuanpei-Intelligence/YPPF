from django.core.management.base import BaseCommand
from django.db import transaction

from app.models import Chat, AcademicQA


class Command(BaseCommand):
    # run it only once!
    help = "Create AcdemicQA objects with their corresponding Chat objects."

    def handle(self, *args, **options):
        directed_chat = Chat.objects.filter(academicqa__isnull=True)
        directed_qas = []
        for c in directed_chat:
            directed_qas.append(AcademicQA(chat=c, directed=True))
        with transaction.atomic():
            AcademicQA.objects.bulk_create(directed_qas)        
