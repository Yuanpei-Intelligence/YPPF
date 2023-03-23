from typing import Callable, ParamSpec, Generic
from datetime import datetime, timedelta

from scheduler.scheduler import scheduler
from scheduler.utils import as_schedule_time


__all__ = ['ScheduleAdder', 'MultipleAdder']


P = ParamSpec('P')


class ScheduleAdder(Generic[P]):
    '''定时任务添加器

    绑定调用的函数，调用时添加对应的定时任务

    Attributes:
        func(Callable): 被绑定的函数
        id(str | None): 任务ID，唯一值
        name(str | None): 用于呈现的任务名称，往往无用，请勿和ID混淆
        run_time(datetime | timedelta | None): 运行的时间
            运行时间，指定时间、时间差或即刻发送
        replace(bool): 替换已存在的任务，默认为True
    '''
    def __init__(
        self, func: Callable[P, None], *,
        id: str | None = None,
        name: str | None = None,
        run_time: datetime | timedelta | None = None,
        replace: bool = True
    ):
        self.func = func
        self.id = id
        self.name = name
        self.run_time = run_time
        self.replace = replace

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> str:
        '''添加定时任务

        Args:
            *args: 与原始函数相同的参数
            **kwargs: 与原始函数相同的参数

        Returns:
            str: 任务ID
        '''
        return scheduler.add_job(
            self.func,
            "date",
            args=args,
            kwargs=kwargs,
            next_run_time=as_schedule_time(self.run_time),
            id=self.id,
            name=self.name,
            replace_existing=self.replace,
        ).id


class MultipleAdder(Generic[P]):
    '''多个定时任务添加器

    Attributes:
        func(Callable): 被绑定的函数

    Methods:
        schedule: 获取单次定时任务添加器
    '''
    def __init__(self, func: Callable[P, None]):
        self.func = func

    def schedule(self, id: str | None = None, name: str | None = None, *,
                 run_time: datetime | timedelta | None = None,
                 replace: bool = True) -> ScheduleAdder[P]:
        '''规划单次定时任务

        Returns:
            ScheduleAdder: 单次定时任务添加器

        References:
            :class:`ScheduleAdder`
            :method:`ScheduleAdder.__init__`
        '''
        return ScheduleAdder(self.func, id=id, name=name, run_time=run_time, replace=replace)


def schedule_adder(
    func: Callable[P, None], *,
    id: str | None = None,
    name: str | None = None,
    run_time: datetime | timedelta | None = None,
    replace: bool = True,
) -> Callable[P, str]:
    '''获取定时任务添加函数

    使用原始函数来生成一个定时任务添加器，该函数接受与原始函数相同的参数，返回任务ID。
    添加的任务参数在调用本函数时传递，以免和原始函数的参数混淆。

    Returns:
        ScheduleAdder: 定时任务添加器，接受与原始函数相同的参数，返回任务ID

    References:
        :class:`ScheduleAdder`
        :module:`scheduler.adder`

    Warning:
        Deprecated: 多任务功能已废弃，请使用 :class:`MultipleAdder` 代替
        DeprecationWarning: 该函数即将废弃，请使用 :class:`ScheduleAdder` 代替
    '''
    return ScheduleAdder(func, id=id, name=name, run_time=run_time, replace=replace)
