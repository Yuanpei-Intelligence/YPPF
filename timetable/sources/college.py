"""
Source of 书院课 (YPPF course activities) the person has selected.
Contract: ``timetable/README.md`` §4.3, §6.5 and §11. Needs the ``app``
application, which is imported lazily inside the query.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from semester.calendar import calendar_between
from timetable.sources.base import (
    DateSpan,
    Occurrence,
    occurrence_sort_key,
    week_span,
)

__all__ = ['CollegeCourseSource']


def _week_monday(on: date) -> date:
    # Monday of the calendar week of ``on``; teaching weeks start on Mondays,
    # so this identifies the week without a term.
    return on - timedelta(days=on.weekday())


class CollegeCourseSource:
    """
    Selected 书院课 (``CourseParticipant.status == SUCCESS``). Per term: the
    courses of the YPPF semester matching ``term.yppf_year_semester()``; per
    date span: every selected course, the dates decide. For every
    ``CourseTime`` and week: a generated course ``Activity`` starting in
    that week supplies the real time/location/status (canceled/aborted ones
    are kept as ``'canceled'``, an attended participation gives
    ``status='checked_in'``); otherwise the weekly time is expanded from
    ``ct.start + 7k days`` for ``k in range(ct.cur_week, ct.end_week)``,
    and such an expanded lesson on a holiday or exam date of the
    university calendar is ``'suspended'`` (README §11; 调休 dates change
    nothing for 书院课, and generated activities keep their own status).
    """

    key = 'college'
    label = '书院课'
    setting = 'show_college'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_college:
            return []
        if week_from > week_to:
            return []
        year_semester = term.yppf_year_semester()
        if year_semester is None:
            return []
        courses = self._courses(person, year_semester)
        if not courses:
            return []
        span_start, span_end = week_span(term, week_from, week_to)
        return self._between(person, courses, span_start, span_end, term.week_of)

    def occurrences_between(self, person, span: DateSpan,
                            settings) -> list[Occurrence]:
        if settings is not None and not settings.show_college:
            return []
        if span.end < span.start:
            return []
        courses = self._courses(person, None)
        if not courses:
            return []
        span_start, span_end = span.bounds()
        return self._between(person, courses, span_start, span_end, span.week_of)

    @staticmethod
    def _courses(person, year_semester) -> list:
        # Successfully selected, not aborted courses; optionally of one
        # YPPF ``(year, Semester)``.
        from app.models import Course, CourseParticipant
        courses = (
            Course.objects
            .exclude(status=Course.Status.ABORT)
            .filter(participant_set__person=person,
                    participant_set__status=CourseParticipant.Status.SUCCESS))
        if year_semester is not None:
            year, semester = year_semester
            courses = courses.filter(year=year, semester__contains=semester.value)
        return list(courses.select_related('organization').distinct().order_by('id'))

    def _between(self, person, courses: list, span_start: datetime,
                 span_end: datetime,
                 week_of: Callable[[date], int]) -> list[Occurrence]:
        # Lessons of ``courses`` starting in ``[span_start, span_end)``.
        from app.models import Activity, CourseTime, Participation
        course_by_id = {course.pk: course for course in courses}
        course_times = list(
            CourseTime.objects.filter(course__in=courses).order_by('start', 'id'))
        activities = list(
            Activity.objects
            .filter(category=Activity.ActivityCategory.COURSE,
                    course_time__in=course_times,
                    start__gte=span_start, start__lt=span_end)
            .order_by('start', 'id'))
        # First generated activity per (course time, week); a week with one
        # is not expanded from the weekly time.
        activities_by_time: dict[int, dict[date, Activity]] = {}
        for activity in activities:
            weeks = activities_by_time.setdefault(activity.course_time_id, {})
            weeks.setdefault(_week_monday(activity.start.date()), activity)
        attended = set(
            Participation.objects
            .filter(person=person, activity__in=activities,
                    status=Participation.AttendStatus.ATTENDED)
            .values_list('activity_id', flat=True))
        excluded_status = (
            Activity.Status.CANCELED, Activity.Status.ABORT, Activity.Status.REJECT,
        )

        result: list[Occurrence] = []
        # Lessons expanded from the weekly time (no generated activity).
        expanded: list[Occurrence] = []
        for course_time in course_times:
            course = course_by_id[course_time.course_id]
            subtitle = course.teacher or course.organization.oname
            generated = activities_by_time.get(course_time.pk, {})
            for activity in generated.values():
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
                    date=on, week=week_of(on), weekday=on.isoweekday(),
                    color_key=course.name,
                    status=status,
                    ref={'course_id': course.pk, 'activity_id': activity.pk},
                ))
            for k in range(course_time.cur_week, course_time.end_week):
                start = course_time.start + timedelta(days=7 * k)
                if not span_start <= start < span_end:
                    continue
                on = start.date()
                if _week_monday(on) in generated:
                    continue
                expanded.append(Occurrence(
                    id=f'college:{course_time.pk}:{on.isoformat()}',
                    source='college', kind='college',
                    title=course.name, subtitle=subtitle,
                    location=course.classroom,
                    start=start, end=course_time.end + timedelta(days=7 * k),
                    date=on, week=week_of(on), weekday=on.isoweekday(),
                    color_key=course.name, status='',
                    ref={'course_id': course.pk, 'activity_id': None},
                ))
        _suspend_on_no_class_days(expanded)
        result.extend(expanded)
        result.sort(key=occurrence_sort_key)
        return result


def _suspend_on_no_class_days(occurrences: list[Occurrence]) -> None:
    # Mark the lessons that fall on a holiday or exam date of the university
    # calendar 'suspended' (README §11): one calendar query, none when empty.
    if not occurrences:
        return
    calendar = calendar_between(min(item.date for item in occurrences),
                                max(item.date for item in occurrences))
    for item in occurrences:
        if not calendar.is_class_day(item.date):
            item.status = 'suspended'
