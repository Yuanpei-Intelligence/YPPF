'''
Create the feedback type that routes preview feedback to the receiving group.
'''
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Max

from app.models import Organization
from feedback.models import FeedbackType
from rollout.config import CONFIG


class Command(BaseCommand):
    help = (
        '创建体验反馈使用的反馈类型，指向 rollout.feedback.org_name 配置的接收小组；'
        '可重复运行'
    )

    def handle(self, *args, **options):
        type_name = CONFIG.feedback_type_name
        org_name = CONFIG.feedback_org_name
        org = (
            Organization.objects.select_related('otype')
            .filter(oname=org_name).first()
        )
        if org is None:
            raise CommandError(
                f'找不到接收小组「{org_name}」。请先在后台创建该小组，'
                '或修改 config.json 中的 rollout.feedback.org_name。'
            )

        existing = FeedbackType.objects.filter(name=type_name).first()
        if existing is not None:
            if (existing.org_id == org.pk
                    and existing.org_type_id == org.otype_id):
                self.stdout.write(
                    f'反馈类型「{type_name}」已指向「{org_name}」，无需修改。')
                return
            raise CommandError(
                f'反馈类型「{type_name}」已存在，但没有指向「{org_name}」。'
                '请在后台核对后再运行本命令。'
            )

        # FeedbackType uses a manually assigned small integer primary key. A
        # concurrent run picking the same id fails on the primary key instead
        # of creating a second type.
        try:
            with transaction.atomic():
                max_id = FeedbackType.objects.aggregate(
                    max_id=Max('id'))['max_id']
                FeedbackType.objects.create(
                    id=(max_id or 0) + 1,
                    name=type_name,
                    org_type=org.otype,
                    org=org,
                    flexible=FeedbackType.Flexible.ALL_DEFAULT,
                )
        except IntegrityError as error:
            raise CommandError(
                '创建反馈类型时与其他写入冲突，请重新运行本命令。') from error
        self.stdout.write(self.style.SUCCESS(
            f'已创建反馈类型「{type_name}」，发往「{org_name}」。'))
