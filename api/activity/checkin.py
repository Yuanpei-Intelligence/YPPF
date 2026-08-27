from datetime import datetime, timedelta

from django.db import transaction

from app.models import Activity, NaturalPerson, Participation
import utils.models.query as SQ


class CheckinError(Exception):
    """Base class for expected activity check-in failures."""


class CheckinActivityNotFound(CheckinError):
    """The requested activity does not exist."""


class CheckinNotRequired(CheckinError):
    """The activity does not use check-in."""


class CheckinClosed(CheckinError):
    """The activity has already ended."""


class CheckinNotOpen(CheckinError):
    """The activity is outside its check-in window."""


class CheckinParticipationNotFound(CheckinError):
    """The person has no eligible participation record."""


def do_checkin(person: NaturalPerson, aid: int) -> str:
    """
    执行活动签到逻辑。

    Args:
        person: 签到的个人（NaturalPerson）
        aid: 活动 ID

    Returns:
        签到成功提示。

    Raises:
        CheckinError: 签到业务条件不满足。
    """
    try:
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)

            if not activity.need_checkin:
                raise CheckinNotRequired("该活动无需签到。")

            if activity.status == Activity.Status.END:
                raise CheckinClosed("活动已结束，不再开放签到。")

            if not (
                activity.status == Activity.Status.PROGRESSING
                or (
                    activity.status == Activity.Status.WAITING
                    and datetime.now() + timedelta(hours=1) >= activity.start
                )
            ):
                raise CheckinNotOpen("活动开始前一小时开放签到，请耐心等待。")

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
                return "您已签到，无需重复签到。"
            participant.status = Participation.AttendStatus.ATTENDED
            participant.save(update_fields=['status'])
            return "签到成功。"
    except Activity.DoesNotExist as exc:
        raise CheckinActivityNotFound("活动不存在。") from exc
    except Participation.DoesNotExist as exc:
        raise CheckinParticipationNotFound("您尚未报名该活动。") from exc
