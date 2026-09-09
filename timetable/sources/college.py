"""
Source of 书院课 (YPPF course activities) the person has selected.
Contract: ``timetable/README.md`` §4.3. Needs the ``app`` application, which
is imported lazily inside ``occurrences``.
"""
from __future__ import annotations

from datetime import timedelta

from timetable.sources.base import Occurrence, occurrence_sort_key, week_span

__all__ = ['CollegeCourseSource']


class CollegeCourseSource:
    """
    Selected 书院课 (``CourseParticipant.status == SUCCESS``) of the YPPF
    semester matching ``term.yppf_year_semester()``. For every ``CourseTime``
    and week: a generated course ``Activity`` starting in that week supplies
    the real time/location/status (canceled/aborted ones are excluded, an
    attended participation gives ``status='checked_in'``); otherwise the
    weekly time is expanded from ``ct.start + 7k days`` for
    ``k in range(ct.cur_week, ct.end_week)``.
    """

    key = 'college'
    label = '书院课'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_college:
            return []
        if week_from > week_to:
            return []
        year_semester = term.yppf_year_semester()
        if year_semester is None:
            return []
        from app.models import (
            Activity, Course, CourseParticipant, CourseTime, Participation,
        )
        year, semester = year_semester
        courses = list(
            Course.objects
            .filter(year=year, semester__contains=semester.value)
            .exclude(status=Course.Status.ABORT)
            .filter(participant_set__person=person,
                    participant_set__status=CourseParticipant.Status.SUCCESS)
            .select_related('organization')
            .distinct()
            .order_by('id'))
        if not courses:
            return []
        course_by_id = {course.pk: course for course in courses}
        course_times = list(
            CourseTime.objects.filter(course__in=courses).order_by('start', 'id'))
        span_start, span_end = week_span(term, week_from, week_to)
        activities = list(
            Activity.objects
            .filter(category=Activity.ActivityCategory.COURSE,
                    course_time__in=course_times,
                    start__gte=span_start, start__lt=span_end)
            .order_by('start', 'id'))
        activity_by_week: dict[tuple[int, int], Activity] = {}
        for activity in activities:
            week = term.week_of(activity.start.date())
            activity_by_week.setdefault((activity.course_time_id, week), activity)
        attended = set(
            Participation.objects
            .filter(person=person, activity__in=activities,
                    status=Participation.AttendStatus.ATTENDED)
            .values_list('activity_id', flat=True))
        excluded_status = (
            Activity.Status.CANCELED, Activity.Status.ABORT, Activity.Status.REJECT,
        )

        result: list[Occurrence] = []
        for course_time in course_times:
            course = course_by_id[course_time.course_id]
            subtitle = course.teacher or course.organization.oname
            weeks_with_activity: set[int] = set()
            for week in range(week_from, week_to + 1):
                activity = activity_by_week.get((course_time.pk, week))
                if activity is None:
                    continue
                weeks_with_activity.add(week)
                on = activity.start.date()
                if activity.status in excluded_status:
                    # Keep the slot visible as 已取消 rather than silently empty.
                    status = 'canceled'
                elif activity.pk in attended:
                    status = 'checked_in'
                else:
                    status = ''
                result.append(Occurrence(
                    id=f'college:{course_time.pk}:{on.isoformat()}',
                    source='college', kind='college',
                    title=course.name, subtitle=subtitle,
                    location=activity.location or course.classroom,
                    start=activity.start, end=activity.end,
                    date=on, week=week, weekday=on.isoweekday(),
                    color_key=course.name,
                    status=status,
                    ref={'course_id': course.pk, 'activity_id': activity.pk},
                ))
            for k in range(course_time.cur_week, course_time.end_week):
                start = course_time.start + timedelta(days=7 * k)
                end = course_time.end + timedelta(days=7 * k)
                on = start.date()
                week = term.week_of(on)
                if week < week_from or week > week_to or week in weeks_with_activity:
                    continue
                result.append(Occurrence(
                    id=f'college:{course_time.pk}:{on.isoformat()}',
                    source='college', kind='college',
                    title=course.name, subtitle=subtitle,
                    location=course.classroom,
                    start=start, end=end,
                    date=on, week=week, weekday=on.isoweekday(),
                    color_key=course.name, status='',
                    ref={'course_id': course.pk, 'activity_id': None},
                ))
        result.sort(key=occurrence_sort_key)
        return result
