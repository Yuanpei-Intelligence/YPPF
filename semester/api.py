from datetime import date

from semester.models import Semester


def current_semester() -> Semester:
    """
    A wrapper for `semester_of`.
    """
    return semester_of(date.today())


def semester_of(date) -> Semester:
    """
    Get semester containing date, or semester just passed.
    Otherwise, raise DoesNotExist.
    """
    try:
        return Semester.objects.get(
            start_date__lte=date, end_date__gte=date)
    except Semester.DoesNotExist:
        return Semester.objects.filter(end_date__lt=date).latest('end_date')
