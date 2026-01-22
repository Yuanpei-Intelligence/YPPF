"""
Utility functions for appointment API.
These functions are extracted from Appointment/views.py to be used in the API module.
"""
from datetime import datetime, timedelta

from Appointment.models import Participant, LongTermAppoint, Room, Room
from Appointment.utils.identity import get_auditor_ids
from Appointment.extern.wechat import MessageType, notify_appoint


def get_content_students(students_id: list[str]) -> list[Participant]:
    """
    Get participants by student IDs.

    Args:
        students_id: List of student IDs

    Returns:
        List of Participant objects

    Raises:
        AssertionError: If students_id is invalid or some students don't exist
    """
    assert isinstance(students_id, list), '预约人信息有误，请检查后重新发起预约！'
    students = Participant.objects.filter(Sid__in=students_id)
    assert len(students) == len(students_id), '预约人信息有误，请检查后重新发起预约！'
    return list(students)


# Note: add_appoint function has been removed.
# All validation logic has been moved to CheckoutAppointView in views.py
# to eliminate redundant parameter passing and checks.


def notify_longterm_review(longterm: LongTermAppoint, auditor_ids: list[str]):
    """
    Notify auditors about a long-term appointment review request.

    Args:
        longterm: LongTermAppoint object
        auditor_ids: List of auditor user IDs
    """
    if not auditor_ids:
        return
    infos = []
    if longterm.get_applicant_id() != longterm.appoint.get_major_id():
        infos.append(f'申请者：{longterm.applicant.name}')
    notify_appoint(
        longterm,
        MessageType.LONGTERM_REVIEWING,
        *infos,
        students_id=auditor_ids,
        url=f'review?Lid={longterm.pk}'
    )


def calculate_appointment_datetime(
    weekday: str,
    startid: int,
    endid: int,
    start_week: int,
    room: Room
) -> tuple[datetime, datetime]:
    """
    Calculate appointment start and end datetime from parameters.

    Args:
        weekday: Weekday string (Mon, Tue, etc.)
        startid: Start time slot ID
        endid: End time slot ID
        start_week: Start week offset (0 for this week, 1 for next week)
        room: Room object

    Returns:
        Tuple of (start_datetime, end_datetime)
    """
    import Appointment.utils.web_func as web_func

    wklist = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    dayrange_list = web_func.get_dayrange(day_offset=0)[0]

    for day in dayrange_list:
        if day['weekday'] == weekday:
            starttime, valid = web_func.get_hour_time(room, startid)
            assert valid is True, '起始时间无效'
            endtime, valid = web_func.get_hour_time(room, endid + 1)
            assert valid is True, '结束时间无效'

            start_datetime = datetime(
                day['year'],
                day['month'],
                day['day'],
                *map(int, starttime.split(":"))
            )
            end_datetime = datetime(
                day['year'],
                day['month'],
                day['day'],
                *map(int, endtime.split(":"))
            )

            # Apply week offset
            start_datetime += timedelta(weeks=start_week)
            end_datetime += timedelta(weeks=start_week)

            return start_datetime, end_datetime

    raise ValueError(f'Invalid weekday: {weekday}')
