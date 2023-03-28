from typing import Callable
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


_periodical_jobs: list[PeriodicalJob] = []


def periodical(trigger: str, job_id: str = '', **trigger_args):
    """Wrap a function into a periodical job.

    If `job_id` is not provided, use function name.

    :param trigger: 'cron' or 'interval'
    :type trigger: str
    """
    def wrapper(fn: Callable[..., None]):
        _job = PeriodicalJob(fn, job_id or fn.__name__, trigger, trigger_args)
        _periodical_jobs.append(_job)
        return fn
    return wrapper
