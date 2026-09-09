"""
Source of 地下室 room appointments of the person.
Contract: ``timetable/README.md`` §4.3. Needs the ``Appointment`` application,
which is imported lazily inside ``occurrences``.
"""
from __future__ import annotations

from timetable.sources.base import Occurrence, occurrence_sort_key, week_span

__all__ = ['AppointSource']


class AppointSource:
    """
    Non-cancelled ``Appoint`` rows where the person's account is the
    ``major_student`` or one of the ``students``, starting inside the week
    range. Title ``地下室 <room>``.
    """

    key = 'appoint'
    label = '预约'

    def occurrences(self, person, term, week_from: int, week_to: int,
                    settings) -> list[Occurrence]:
        if settings is not None and not settings.show_appointments:
            return []
        if week_from > week_to:
            return []
        from django.db.models import Q

        from Appointment.models import Appoint
        user = person.get_user()
        span_start, span_end = week_span(term, week_from, week_to)
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
                date=on, week=term.week_of(on), weekday=on.isoweekday(),
                color_key='appoint', status='',
                ref={'appoint_id': appoint.Aid},
            ))
        result.sort(key=occurrence_sort_key)
        return result
