from typing import Callable, Generic, ParamSpec, TypeVar, Concatenate, overload
from functools import partial

__all__ = [
    'constructor',
    'check_method',
]

P = ParamSpec('P')
T = TypeVar('T')

class constructor(Generic[P, T]):
    def __init__(self, func: Callable[Concatenate[T, P], T]):
        self.func = func

    @overload
    def __get__(self, instance: T, owner: type[T]) -> Callable[P, T]: ...
    @overload
    def __get__(self, instance: None, owner: type[T]) -> Callable[P, T]: ...

    def __get__(
        self, instance: object, owner: type | None = None
    ) -> Callable[P, T]:
        if instance is None and isinstance(owner, type):
            instance = owner()
        return self.func.__get__(instance, owner)

class check_method(Generic[P, T]):
    def __init__(self, func: Callable[Concatenate[T, T, P], bool]) -> None:
        self.func = classmethod(func)

    def __get__(
        self, instance: object, owner: type | None = None
    ) -> Callable[Concatenate[T, P], bool] | Callable[P, bool]:
        func = self.func.__get__(instance, owner)  # type: ignore
        if instance is None:
            return func
        return partial(func, instance)  # type: ignore
