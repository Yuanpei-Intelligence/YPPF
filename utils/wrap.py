from typing import Callable, TypeVar, ParamSpec, cast, Any, overload, Literal
from functools import wraps

__all__ = [
    'value_on_except',
    'return_on_except',
    'stringify_to',
]

P = ParamSpec('P')
R = TypeVar('R')
RR = TypeVar('RR')
E = TypeVar('E', bound=Exception)


ExceptValue = R | Callable[[], R] | Callable[[E], R]
Listener = Callable[[E, tuple[Any, ...], dict[str, Any]], None]


def value_on_except(value: ExceptValue[R, E],
                    exc_info: E) -> R:
    '''当函数抛出异常时返回指定值

    Notes:
        当``value``为函数时，先将异常信息作为参数传入
        如果抛出``TypeError``则不传入参数
    '''
    if callable(value):
        try:
            return cast(Callable[[E], R], value)(exc_info)
        except TypeError:
            return cast(Callable[[], R], value)()
    return value


@overload
def return_on_except(
    value: R | Callable[[], R] | Callable[[E], R],
    exc_type: type[E] | tuple[type[E], ...],
    *listeners: Callable[[E, tuple[Any, ...], dict[str, Any]], None],
    merge_type: Literal[False] = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

@overload
def return_on_except(
    value: R | Callable[[], R] | Callable[[E], R],
    exc_type: type[E] | tuple[type[E], ...],
    *listeners: Callable[[E, tuple[Any, ...], dict[str, Any]], None],
    merge_type: Literal[True] = ...,
) -> Callable[[Callable[P, RR]], Callable[P, RR | R]]: ...

def return_on_except(
    value: ExceptValue[R, E],
    exc_type: type[E] | tuple[type[E], ...],
    *listeners: Listener[E],
    merge_type: bool = False,
) -> Callable[[Callable[P, RR]], Callable[P, RR | R]]:
    '''提供包装器，当函数抛出指定异常时返回指定值

    Args:
        value(ExceptValue[R, E]): 当函数抛出异常时返回的值，
            可以是值、工厂或异常处理函数
        exc_type(type[E] | tuple[type[E], ...]): 指定的异常类型
        *listeners(Callable[[E, tuple, dict], None]): 异常信号接收函数

    Keyword Args:
        merge_type(bool): 合并返回值类型提示，默认要求返回值类型与原函数一致，
            同类型如不同布尔值等则不会报错

    Returns:
        Callable[[Callable[P, R]], Callable[P, R]]: 处理指定异常的包装器

    Examples:
        返回常量是最常用的方法，用于检查是否失败::

            @return_on_except(False, Exception)
            def func():
                return True

        可以使用工厂函数生成对象::

            @return_on_except(list[str], KeyError)
            def get_args(content: dict) -> list[str]:
                return content['args']

            >>> get_args({'args': ['a', 'b']})
            ['a', 'b']
            >>> get_args({})
            []
    '''
    def wrapper(func: Callable[P, RR]):
        @wraps(func)
        def inner(*args: P.args, **kwargs: P.kwargs):
            try:
                return func(*args, **kwargs)
            except exc_type as exc:
                for listener in listeners:
                    listener(exc, args, kwargs)
                return value_on_except(value, exc)
        return inner
    return wrapper


def stringify_to(value_func: Callable[[str], R]) -> Callable[[Exception], R]:
    '''将异常信息通过str转换为返回值的函数

    进行检查后，将异常信息转换为字符串，再转换为返回值
    主要用于捕获单参数异常，如``AssertionError``等

    Args:
        value_func(Callable[[str], R]): 将字符串转换为返回值的函数

    Returns:
        Callable[[Exception], R]: 将异常信息转换为返回值的函数，
            当不传入异常信息或传入的异常信息不是恰好一个参数的异常时抛出异常
    '''
    @wraps(value_func)
    def wrapper(exc_info: Exception) -> R:
        assert isinstance(exc_info, Exception)
        assert len(exc_info.args) == 1
        # str(exc_info) 应当等价于 str(exc_info.args[0])
        return value_func(str(exc_info))
    return wrapper
