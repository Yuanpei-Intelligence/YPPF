"""
Source of 地下室 room appointments of the person.
Contract: ``timetable/README.md`` §4.3 and §6.5. Needs the ``Appointment``
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

__all__ = ['AppointSource']


class AppointSource:
    """
    Non-cancelled ``Appoint`` rows where the person's account is the
    ``major_student`` or one of the ``students``, starting inside the
    queried range. Title ``地下室 <room>``. Date-based: the term only
    supplies the week numbers.
    """

    key = 'appoint'
    label = '预约'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_appointments:
            return []
        if week_from > week_to:
            return []
        span_start, span_end = week_span(term, week_from, week_to)
        return self._between(person, span_start, span_end, term.week_of)

    def occurrences_between(self, person, span: DateSpan,
                            settings) -> list[Occurrence]:
        if settings is not None and not settings.show_appointments:
            return []
        if span.end < span.start:
            return []
        span_start, span_end = span.bounds()
        return self._between(person, span_start, span_end, span.week_of)

    def _between(self, person, span_start: datetime, span_end: datetime,
                 week_of: Callable[[date], int]) -> list[Occurrence]:
        # Appointments starting in ``[span_start, span_end)``.
        from django.db.models import Q

        from Appointment.models import Appoint
        user = person.get_user()
        appoints = (
            Appoint.objects.not_canceled()
            .filter(Q(major_student__Sid=user) | Q(students__Sid=user))
            .filter(Astart__gte=span_start, Astart__lt=span_end)
            .select_related('Room')
            .distinct()
            .order_by('Astart', 'Aid'))
        result: list[Occurrence] = []
        for appoint in appoints:
            room = appoint.Room
            if room is None:
                room_name, room_id = '', ''
            else:
                room_name, room_id = room.Rtitle or room.Rid, room.Rid
            on = appoint.Astart.date()
            result.append(Occurrence(
                id=f'appoint:{appoint.Aid}:{on.isoformat()}',
                source='appoint', kind='appoint',
                title=f'地下室 {room_name}'.strip(),
                subtitle=appoint.Ausage or '',
                location=room_id,
                start=appoint.Astart, end=appoint.Afinish,
                date=on, week=week_of(on), weekday=on.isoweekday(),
                color_key='appoint', status='',
                ref={'appoint_id': appoint.Aid},
            ))
        result.sort(key=occurrence_sort_key)
        return result
