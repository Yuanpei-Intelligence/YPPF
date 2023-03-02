from typing import Callable, ParamSpec
from datetime import datetime, timedelta
from functools import wraps

from extern.config import wechat_config as CONFIG
from scheduler.scheduler import scheduler


__all__ = [
    'scheduler_enabled',
    'get_caller',
]


def scheduler_enabled(multithread: bool = True) -> bool:
    '''判断定时任务是否可用'''
    return multithread and CONFIG.multithread


P = ParamSpec('P')
def get_caller(func: Callable[P, None], *, multithread: bool = True,
               run_time: datetime | timedelta | None = None,
               job_id: str | None = None, replace: bool = True):
    '''获取函数的调用者'''
    if not scheduler_enabled(multithread):
        return func
    @wraps(func)
    def _func(*args: P.args, **kwargs: P.kwargs):
        if isinstance(run_time, datetime):
            _next_run = run_time
        elif isinstance(run_time, timedelta):
            _next_run = datetime.now() + run_time
        else:
            _next_run = datetime.now() + timedelta(seconds=5)
        scheduler.add_job(
            func,
            "date",
            args=args,
            kwargs=kwargs,
            next_run_time=_next_run,
            id=job_id,
            replace_existing=replace,
        )
    return _func
