'''定时任务添加器

本模块实现定时任务添加器，用于添加定时任务，支持多个任务的添加。

:class:`ScheduleAdder` 用于添加单个任务，
:class:`MultipleAdder` 用于添加多个任务。

Examples:
    假设有一个函数，需要在指定时间执行::

        import logging
        from datetime import datetime, timedelta
        def func(a, b, c):
            logging.info('a=%s, b=%s, c=%s', a, b, c)

    使用 :class:`ScheduleAdder` 添加单个任务::

        single_adder = ScheduleAdder(func, run_time=datetime(2023, 1, 1))
        single_adder(1, 2, 3)

    使用 :class:`MultipleAdder` 添加多个任务::

        job_adder = MultipleAdder(func)
        job_adder.schedule('schedule', run_time=datetime(2023, 1, 1))(1, 2, 3)
        adder_later = job_adder.schedule('later', run_time=timedelta(minutes=5))
        adder_later(4, 5, 6)
        job_adder.schedule()(7, 8, 9)
'''
from typing import Callable, ParamSpec, Generic
from datetime import datetime, timedelta

from utils.marker import fix_me
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
        replace(bool): 是否替换已存在的任务
    '''
    def __init__(
        self, func: Callable[P, None], *,
        id: str | None = None,
        name: str | None = None,
        run_time: datetime | timedelta | None = None,
        replace: bool = True
    ):
        '''创建定时任务添加器

        绑定调用函数并记录任务参数，调用时添加对应的定时任务。

        Args:
            func(Callable): 被绑定的函数

        Keyword Args:
            id(str, optional): 任务ID，唯一值
            name(str, optional): 用于呈现的任务名称，请勿和ID混淆
            run_time(datetime | timedelta, optional): 运行的时间
                运行时间，指定时间、时间差或即刻发送，默认在短暂延迟后立刻发送
            replace(bool, optional): 替换已存在的任务，默认为True
        '''
        self.func = func
        self.id = id
        self.name = name
        self.run_time = run_time
        self.replace = replace

    # TODO: 返回值是干嘛的？找一下 commit 记录，之前返回 id，现在 return Job，不确定作用
    @fix_me
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> str:
        '''添加定时任务

        Args:
            *args: 与原始函数相同的参数
            **kwargs: 与原始函数相同的参数

        Returns:
            str: 任务ID
        '''
        # next_run_time用于强制指定下次运行时间，run_date传递给date触发器
        # 基本相同，对于date触发器，后者可能更准确
        # See https://apscheduler.readthedocs.io/en/3.x/modules/triggers/date.html
        return scheduler.add_job(
            self.func,
            "date",
            args=args,
            kwargs=kwargs,
            run_date=as_schedule_time(self.run_time),
            id=self.id,
            name=self.name,
            replace_existing=self.replace,
        )


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
