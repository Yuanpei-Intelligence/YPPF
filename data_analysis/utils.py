from datetime import datetime
from typing import Any, Callable, List, Union

from django.db import models
from django.db.models import QuerySet

from app.models import Semester

ValueList = List[List[Any]]


def desensitize(data: ValueList, hash_func: Callable,
                idx_list: List[int] = [0]) -> ValueList:
    """Desensitize data with hash.

    :param data: data to be desensitized
    :type data: ValueList
    :param hash_func: hash function
    :type hash_func: Callable
    :param idx_list: columns to be desensitized, defaults to [0]
    :type idx_list: List[int], optional
    :return: _description_
    :rtype: ValueList
    """
    for line in data:
        for idx in idx_list:
            line[idx] = hash_func(line[idx])
    return data


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
