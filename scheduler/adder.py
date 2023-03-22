from typing import Callable, ParamSpec, TypeVar, cast
from datetime import datetime, timedelta

from scheduler.scheduler import scheduler
from scheduler.utils import as_schedule_time


__all__ = ['schedule_adder']

P = ParamSpec('P')
T = TypeVar('T')

Seq = list[T] | tuple[T, ...]
SeqOrVal = Seq[T] | T

def _generator(source: SeqOrVal[T]):
    if not isinstance(source, list | tuple):
        while True: yield cast(T, source)
    else:
        yield from cast(Seq[T], source)


def schedule_adder(
    func: Callable[P, None], *,
    id: SeqOrVal[str | None] = None,
    name: SeqOrVal[str | None] = None,
    run_time: SeqOrVal[datetime | timedelta | None] = None,
    replace: bool = True,
) -> Callable[P, str]:
    '''获取定时任务添加函数

    使用原始函数来生成一个定时任务添加器，该函数接受与原始函数相同的参数，返回任务ID。
    添加的任务参数在调用本函数时传递，以免和原始函数的参数混淆。
    序列参数被用于重复调用时添加不同的任务，如果不是序列，则每次调用时都使用相同的值。
    序列参数不会被复制，不会循环，请避免中途修改导致的问题。
    
    Args:
        func(Callable): 原始函数

    Keyword Args:
        id(str | None, optional): 任务ID，唯一值，序列或单值
        name(str | None, optional): 用于呈现的任务名称，往往无用，请勿和ID混淆
        run_time(datetime | timedelta | None, optional): 运行的时间运行时间，指定时间、时间差或即刻发送
        replace(bool, optional): 替换已存在的任务，默认为True

    Returns:
        Callable: 定时任务添加函数，接受与原始函数相同的参数，返回任务ID

    Raises:
        这个函数并不抛出异常，但是添加任务时可能会抛出异常，如：
        StopIteration: 序列参数长度不足，调用次数超过序列长度

    Examples:
        通常情况下，使用该函数直接添加单个任务，不需要保存返回值，
        任务一般通过日志来查看结果，因为定时任务的执行结果不会返回给调用者::

            import logging
            def func(a, b, c):
                logging.info('a=%s, b=%s, c=%s', a, b, c)
            adder = schedule_adder(func)
            adder(1, 2, 3)

    Todo:
        * 返回值类型应该是一个类，而不是函数，以便于添加更多的功能并提供类型提示
        * Raises部分应该移动到返回值的类中
    '''
    _ids = _generator(id)
    _names = _generator(name)
    _run_times = _generator(run_time)
    def _adder(*args: P.args, **kwargs: P.kwargs):
        return scheduler.add_job(
            func,
            "date",
            args=args,
            kwargs=kwargs,
            next_run_time=as_schedule_time(next(_run_times)),
            id=next(_ids),
            name=next(_names),
            replace_existing=replace,
        ).id
    return _adder
