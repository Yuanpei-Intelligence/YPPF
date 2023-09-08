from datetime import date

from django.db.models import Q

from semester.models import Semester


def current_semester(allow_fallback: bool = True) -> Semester:
    """
    A wrapper for `semester_of`.
    """
    return semester_of(date.today(), allow_fallback)


def next_semester() -> Semester:
    """
    Get next semester.
    """
    today = date.today()
    return Semester.objects.filter(start_date__gt=today).earliest('start_date')


def semester_of(date, allow_fallback: bool = True) -> Semester:
    """
    Get semester containing date.
    If no semester contains date and `fallback` is `True`, return the semester just passed.
    Otherwise, raise Exception.
    """
    q = Q(start_date__lte=date)
    if not allow_fallback:
        q = q & Q(end_date__gte=date)
    return Semester.objects.filter(q).latest('start_date')
