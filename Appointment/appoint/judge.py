from django.db import transaction

from Appointment.models import User, Participant, Appoint
from Appointment.utils.log import get_user_logger, logger


@logger.secure_func('无法设置违规原因', fail_value=False)
def set_appoint_reason(input_appoint: Appoint, reason: Appoint.Reason) -> bool:
    '''预约的过程中检查迟到，先记录原因，并且进入到进行中状态，不一定扣分'''
    with transaction.atomic():
        appoint: Appoint = Appoint.objects.select_for_update().get(
            Aid=input_appoint.Aid)
        if appoint.Astatus == Appoint.Status.APPOINTED:
            appoint.Astatus = Appoint.Status.PROCESSING # 避免重复调用本函数
        appoint.Areason = reason
        appoint.save()

    log_msg = f"预约{appoint.Aid}出现违约:{appoint.get_Areason_display()}"
    get_user_logger(appoint).info(log_msg)
    return True


@logger.secure_func('无法设置违规', fail_value=False)
def appoint_violate(input_appoint: Appoint, reason: Appoint.Reason) -> bool:
    '''将一个预约设为违约'''
    with transaction.atomic():
        appoint: Appoint = Appoint.objects.select_related(
            'major_student').select_for_update().get(Aid=input_appoint.Aid)
        major_student: Participant = Participant.objects.select_for_update().get(
            pk=appoint.major_student.pk)

        if appoint.Astatus == Appoint.Status.VIOLATED:
            return True
        # 不出现负分；如果已经是violated了就不重复扣分了
        deduct = -User.objects.modify_credit(major_student.Sid, -1, '地下室：违规')
        appoint.Astatus = Appoint.Status.VIOLATED
        appoint.Areason = reason
        appoint.save()

    log_msg = f"预约{appoint.Aid}出现违约:{appoint.get_Areason_display()};"
    log_msg += f"扣除信用分:{deduct};剩余信用分:{major_student.credit}"
    get_user_logger(major_student).info(log_msg)
    return True
