"""
Source of YPPF activities the person applied to.
Contract: ``timetable/README.md`` §4.3. Needs the ``app`` application, which
is imported lazily inside ``occurrences``.
"""
from __future__ import annotations

from timetable.sources.base import Occurrence, occurrence_sort_key, week_span

__all__ = ['ActivitySource']


class ActivitySource:
    """
    Activities (not course activities) the person applied to — participation
    in APPLYSUCCESS / ATTENDED / UNATTENDED — that start inside the week
    range and are not canceled, rejected or aborted.
    """

    key = 'activity'
    label = '活动'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_activities:
            return []
        if week_from > week_to:
            return []
        from app.models import Activity, Participation
        span_start, span_end = week_span(term, week_from, week_to)
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
                date=on, week=term.week_of(on), weekday=on.isoweekday(),
                color_key=activity.title, status=status,
                ref={'activity_id': activity.pk},
            ))
        result.sort(key=occurrence_sort_key)
        return result
