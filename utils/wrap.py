from typing import Callable, TypeVar, ParamSpec, cast, Any
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
    if callable(value):
        try:
            return cast(Callable[[E], R], value)(exc_info)
        except TypeError:
            return cast(Callable[[], R], value)()
    return value


def return_on_except(
    value: ExceptValue[R, E],
    exc_type: type[E] | tuple[type[E], ...],
    *listeners: Listener[E],
    merge_type: bool = False,
) -> Callable[[Callable[P, RR]], Callable[P, RR | R]]:
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
    @wraps(value_func)
    def wrapper(exc_info: Exception) -> R:
        assert isinstance(exc_info, Exception)
        assert len(exc_info.args) == 1
        # str(exc_info) 应当等价于 str(exc_info.args[0])
        return value_func(str(exc_info))
    return wrapper
