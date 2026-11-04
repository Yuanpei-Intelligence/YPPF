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
        aid = int(aid)
    except (ValueError, TypeError):
        return False, "签到失败!"

    try:
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)

            if not activity.need_checkin:
                return False, "该活动无需签到。"

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
    except Activity.DoesNotExist:
        return False, "签到失败!"
    except Participation.DoesNotExist:
        # 书院课补选同学：活动发布时按当时名单建 Participation，补选后可能缺失，
        # 此处惰性补建后再签到(issue #973-2)。
        # 注意：此分支在 atomic 块外执行，活动锁已释放。并发重试可能插入重复行
        # 且 current_participants 不同步（Participation 无 (activity, person) 唯一约束）。
        # 若需严格并发安全，应将资格复核、补建、计数与状态转换全部移入 atomic 块内。
        if (activity.category == Activity.ActivityCategory.COURSE
                and activity.course_time is not None):
            from app.models import Course, CourseParticipant
            course = activity.course_time.course
            if CourseParticipant.objects.filter(
                    course=course, person=person,
                    status=CourseParticipant.Status.SUCCESS).exists():
                initial = (Participation.AttendStatus.UNATTENDED
                           if activity.status == Activity.Status.PROGRESSING
                           else Participation.AttendStatus.APPLYSUCCESS)
                participation, created = Participation.objects.get_or_create(
                    activity=activity, person=person,
                    defaults={'status': initial})
                if (not created
                        and participation.status
                        == Participation.AttendStatus.CANCELED):
                    participation.status = initial
                    participation.save(update_fields=['status'])
                if (activity.status == Activity.Status.PROGRESSING
                        or (activity.status == Activity.Status.WAITING
                            and datetime.now() + timedelta(hours=1)
                            >= activity.start)):
                    Participation.objects.filter(
                        activity=activity, person=person).update(
                        status=Participation.AttendStatus.ATTENDED)
                    return True, "签到成功!"
                return False, "活动开始前一小时开放签到，请耐心等待!"
        return False, "您尚未报名该活动!"
