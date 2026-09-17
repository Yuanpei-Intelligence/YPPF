"""地下室使用规范的阅读状态及住宿协议前置检查。"""

from django.db import transaction

from Appointment.models import Participant
from dormitory.models import Agreement


def needs_dormitory_agreement(user):
    """沿用住宿协议规则：仅业务有效的学生账户需要签署。"""
    return (user.active and user.is_student()
            and not Agreement.objects.filter(user=user).exists())


def mark_instructions_read(user):
    """仅记录当前账户的阅读确认；重复确认不改变其他状态。"""
    with transaction.atomic():
        participant = Participant.objects.select_for_update().get(Sid=user)
        if not participant.has_read_instructions:
            participant.has_read_instructions = True
            participant.save(update_fields=['has_read_instructions'])
