from typing import Callable, overload, Literal
from datetime import datetime, tzinfo
from dataclasses import dataclass


__all__ = ['periodical']


@dataclass
class PeriodicalJob:
    """
    Wrap a function as a periodical job.
    Notice that it is not a callable.
    """
    function: Callable[..., None]
    job_id: str
    trigger: str
    tg_args: dict[str, int]

_periodical_jobs: list[PeriodicalJob]


@overload
def periodical(
    trigger: Literal['cron'], job_id: str = '', *,
    year: int | str = ..., month: int | str = ..., day: int | str = ...,
    week: int | str = ..., day_of_week: int | str = ...,
    hour: int | str = ..., minute: int | str = ..., second: int | str = ...,
    start_date: datetime | str = ..., end_date: datetime | str = ..., timezone: tzinfo | str = ...,
    jitter: int | None = ...
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    '''Wrap a function into a cron job.

    If `job_id` is not provided, use function name.

    :ref: https://apscheduler.readthedocs.io/en/latest/modules/triggers/cron.html
    '''

@overload
def periodical(
    trigger: Literal['interval'], job_id: str = '', *,
    weeks: int = 0, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0,
    start_date: datetime | str = ..., end_date: datetime | str = ..., timezone: tzinfo | str = ...,
    jitter: int | None = ...
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    '''Wrap a function into a interval job.

    If `job_id` is not provided, use function name.

    :ref: https://apscheduler.readthedocs.io/en/latest/modules/triggers/interval.html
    '''
