from typing import Callable, ParamSpec, Any
from datetime import datetime, timedelta

from extern.config import wechat_config as CONFIG
from scheduler.adder import ScheduleAdder


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
               job_id: str | None = None, replace: bool = True) -> Callable[P, None]:
    '''获取函数的调用者'''
    if not scheduler_enabled(multithread):
        return func
    adder = ScheduleAdder(func, run_time=run_time, id=job_id, replace=replace)
    # 不应使用返回值，但要确保调用参数正确
    adder: Callable[P, Any]
    return adder  # type: ignore
