from typing import Callable, Generic, ParamSpec, TypeVar, Concatenate, overload

_P = ParamSpec('_P')
_T = TypeVar('_T')
_V = TypeVar('_V')

class constructor(Generic[_P, _T]):
    def __init__(self, func: Callable[Concatenate[_T, _P], _T]): ...
    @overload
    def __get__(self, instance: _T, owner: type[_T]) -> Callable[_P, _T]: ...
    @overload
    def __get__(self, instance: None, owner: type[_T]) -> Callable[_P, _T]: ...

class check_method(classmethod[_T, Concatenate[_V, _P], bool]):
    @overload
    def __get__(self, instance: _T, owner: type[_T]) -> Callable[_P, bool]: ...
    @overload
    def __get__(self, instance: None, owner: type[_T]) -> Callable[Concatenate[_V, _P], bool]: ...
