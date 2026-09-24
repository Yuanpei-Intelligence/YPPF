"""
Website (non-API) views of the timetable app: the public ICS feed.
"""
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

from timetable.ics import build_ics
from timetable.models import TimetableSettings

__all__ = ['ics_feed']


@require_GET
def ics_feed(request, token):
    """
    ``GET /timetable/ics/<token>.ics`` — the calendar of the person whose
    ``TimetableSettings.ics_token`` is ``token``. Deliberately unauthenticated
    (calendar clients cannot log in): the unguessable token is the credential
    and rotating it in the mini-program invalidates old URLs. Unknown tokens
    give 404. Read-only; nothing is mutated.
    """
    try:
        settings = TimetableSettings.objects.select_related('person').get(
            ics_token=token)
    except TimetableSettings.DoesNotExist:
        raise Http404('unknown calendar token')
    response = HttpResponse(
        build_ics(settings.person),
        content_type='text/calendar; charset=utf-8')
    response['Cache-Control'] = 'private, max-age=3600'
    response['Content-Disposition'] = 'inline; filename="timetable.ics"'
    return response
