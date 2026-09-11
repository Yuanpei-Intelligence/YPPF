"""
Source of YPPF activities the person applied to.
Contract: ``timetable/README.md`` §4.3 and §6.5. Needs the ``app``
application, which is imported lazily inside the query.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from timetable.sources.base import (
    DateSpan,
    Occurrence,
    occurrence_sort_key,
    week_span,
)

__all__ = ['ActivitySource']


class ActivitySource:
    """
    Activities (not course activities) the person applied to — participation
    in APPLYSUCCESS / ATTENDED / UNATTENDED — that start inside the queried
    range and are not canceled, rejected or aborted. Date-based: the term
    only supplies the week numbers.
    """

    key = 'activity'
    label = '活动'
    setting = 'show_activities'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_activities:
            return []
        if week_from > week_to:
            return []
        span_start, span_end = week_span(term, week_from, week_to)
        return self._between(person, span_start, span_end, term.week_of)

    def occurrences_between(self, person, span: DateSpan,
                            settings) -> list[Occurrence]:
        if settings is not None and not settings.show_activities:
            return []
        if span.end < span.start:
            return []
        span_start, span_end = span.bounds()
        return self._between(person, span_start, span_end, span.week_of)

    def _between(self, person, span_start: datetime, span_end: datetime,
                 week_of: Callable[[date], int]) -> list[Occurrence]:
        # Activities starting in ``[span_start, span_end)``.
        from app.models import Activity, Participation
        participations = (
            Participation.objects
            .filter(person=person,
                    status__in=[
                        Participation.AttendStatus.APPLYSUCCESS,
                        Participation.AttendStatus.ATTENDED,
                        Participation.AttendStatus.UNATTENDED,
                    ],
                    activity__start__gte=span_start,
                    activity__start__lt=span_end)
            .exclude(activity__category=Activity.ActivityCategory.COURSE)
            .exclude(activity__status__in=[
                Activity.Status.CANCELED,
                Activity.Status.REJECT,
                Activity.Status.ABORT,
            ])
            .select_related('activity', 'activity__organization_id')
            .order_by('activity__start', 'activity_id'))
        result: list[Occurrence] = []
        seen: set[int] = set()
        for participation in participations:
            activity = participation.activity
            if activity.pk in seen:
                continue
            seen.add(activity.pk)
            if participation.status == Participation.AttendStatus.ATTENDED:
                status = 'checked_in'
            elif participation.status == Participation.AttendStatus.APPLYSUCCESS:
                status = 'applied'
            else:
                status = ''
            on = activity.start.date()
            result.append(Occurrence(
                id=f'activity:{activity.pk}:{on.isoformat()}',
                source='activity', kind='activity',
                title=activity.title,
                subtitle=activity.organization_id.oname,
                location=activity.location,
                start=activity.start, end=activity.end,
                date=on, week=week_of(on), weekday=on.isoweekday(),
                color_key=activity.title, status=status,
                ref={'activity_id': activity.pk},
            ))
        result.sort(key=occurrence_sort_key)
        return result
