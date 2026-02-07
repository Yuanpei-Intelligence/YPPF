from app.models import (
    User,
    NaturalPerson,
    Organization,
    Organization as Org,
    OrganizationType as OrgType,
    Position,
    Activity,
    Participation,
    Notification,
    ActivityPhoto,
)
from django.db import transaction
from datetime import datetime, timedelta
import utils.models.query as SQ


def do_checkin(person: NaturalPerson, aid: int) -> tuple[bool, str]:
    """
    执行活动签到逻辑。

    Args:
        person: 签到的个人（NaturalPerson）
        aid: 活动 ID

    Returns:
        (success, message): 是否成功及提示信息
    """
    try:
        activity = Activity.objects.get(id=aid)
    except (Activity.DoesNotExist, ValueError, TypeError):
        return False, "签到失败!"

    if activity.status == Activity.Status.END:
        return False, "活动已结束，不再开放签到。"

    if not (
        activity.status == Activity.Status.PROGRESSING
        or (
            activity.status == Activity.Status.WAITING
            and datetime.now() + timedelta(hours=1) >= activity.start
        )
    ):
        return False, "活动开始前一小时开放签到，请耐心等待!"

    try:
        with transaction.atomic():
            participant = Participation.objects.select_for_update().get(
                SQ.sq(Participation.activity, activity),
                SQ.sq(Participation.person, person),
                status__in=[
                    Participation.AttendStatus.UNATTENDED,
                    Participation.AttendStatus.APPLYSUCCESS,
                    Participation.AttendStatus.ATTENDED,
                ],
            )
            if participant.status == Participation.AttendStatus.ATTENDED:
                return True, "您已签到，无需重复签到!"
            participant.status = Participation.AttendStatus.ATTENDED
            participant.save()
            return True, "签到成功!"
    except Participation.DoesNotExist:
        return False, "您尚未报名该活动!"
