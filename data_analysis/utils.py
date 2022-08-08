from datetime import datetime
from typing import Any, List, Union

from django.db import models
from django.db.models import QuerySet

from app.models import Semester


def time_filter(
        cls: Union[models.Model, QuerySet],
        start_time: datetime = None,
        end_time: datetime = None,
        start_time_field: str = 'time',
        end_time_field: str = 'time',
        year: int = None,
        semester: Semester = None,
        ) -> QuerySet:
    """Time Filter 

    :param cls: Model or QuerySet
    :type cls: Union[models.Model, QuerySet]
    :return: filtered queryset
    :rtype: QuerySet
    """
    filter_kw = {}
    if start_time is not None:
        filter_kw[f'{start_time_field}__gt'] = start_time
    if end_time is not None:
        filter_kw[f'{end_time_field}__lt'] = end_time
    if year is not None:
        filter_kw['year'] = year
    if semester is not None:
        filter['semester'] = semester
    if isinstance(cls, QuerySet):
        return cls.filter(**filter_kw)
    return cls.objects.filter(**filter_kw)
