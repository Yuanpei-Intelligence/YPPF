"""
A module for log utilities. 

It provides consistent log level and format, and always write to
*logger_name.log* file.
The project should use this instead of standard `logging` module.

Differences with `logging.getLogger`:

1. Multiple level logger is not supported. 
2. Exception backtracing stack is fixed.

According to
https://stackoverflow.com/questions/47968861/does-python-logging-support-multiprocessing,
logging within pipe_size, which is usually 4096 btyes, is atomic. 
It is big enough for most of the situation, except for backtracing.
Have to restrict backtrace level.
"""

import os
import json
import logging
from typing import Callable, Any, cast, ParamSpec, Concatenate, TypeVar
from functools import wraps

from django.conf import settings

from boot.config import absolute_path
from utils.http.dependency import HttpRequest
from record.log.config import log_config as CONFIG
from utils.inspect import module_filepath
from utils.wrap import ExceptType


__all__ = [
    'Logger',
]


_loggers: dict[str, 'Logger'] = dict()
P = ParamSpec('P')
T = TypeVar('T')
ReturnType = T | Callable[[], T]


class Logger(logging.Logger):
    @classmethod
    def getLogger(cls, name: str, setup: bool = True):
        if name in _loggers:
            return cast(cls, _loggers[name])
        _logger_class  = logging.getLoggerClass()
        logging.setLoggerClass(cls)
        logger = cast(cls, logging.getLogger(name))
        logging.setLoggerClass(_logger_class)
        if setup:
            logger.setup(name)
        _loggers[name] = logger
        return logger

    def setup(self, name: str, handle: bool = True) -> None:
        self.set_debug_mode(settings.DEBUG)
        self.setLevel()
        if handle: self.add_default_handler(name)

    def setLevel(self, level: int | str | None = None) -> None:
        super().setLevel(CONFIG.level if level is None else level)

    def add_default_handler(self, name: str, *paths: str, format: str = '') -> None:
        base_dir = absolute_path(CONFIG.log_dir)
        for path in paths:
            base_dir = os.path.join(base_dir, path)
            if not os.path.exists(base_dir):
                os.mkdir(base_dir)
        file_path = os.path.join(base_dir, name + '.log')
        handler = logging.FileHandler(file_path, encoding='UTF8', mode='a')
        handler.setFormatter(logging.Formatter(format or CONFIG.format, style='{'))
        self.addHandler(handler)

    def set_debug_mode(self, debug: bool) -> None:
        self.debug_mode = debug

    def findCaller(self, stack_info: bool = False, stacklevel: int = 1):
        filepath, lineno, funcname, sinfo = super().findCaller(stack_info, stacklevel + 1)
        filepath = module_filepath(filepath)
        return filepath, lineno, funcname, sinfo

    def makeRecord(self, *args, **kwargs):
        record = super().makeRecord(*args, **kwargs)
        try:
            record.module, record.filename = record.pathname.rsplit('.', 1)
        except:
            record.module, record.filename = record.pathname, record.pathname
        return record

    def _log(self, level, msg, args, exc_info = None, extra = None,
             stack_info = False, stacklevel = 1) -> None:
        if stack_info:
            stacklevel += CONFIG.stack_level
        stacklevel += 1
        return super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)

    @staticmethod
    def format_request(request: HttpRequest) -> str:
        ret = []
        ret.append('URL: ' + request.get_full_path())
        if request.user.is_authenticated:
            ret.append('User: ' + request.user.__str__())  # Traceable Call
        if request.method is not None:
            ret.append('Method: ' + request.method)
            if request.method.lower() == 'POST':
                try:
                    ret.append('Data: ' + json.dumps(request.POST.dict()))
                except:
                    ret.append('Failed to jsonify post data.')
        return '\n'.join(ret)

    def on_exception(self, message: str = '', *,
                     request: HttpRequest | None = None,
                     raise_exc: bool | None = None) -> None:
        '''
        Log exception and raise it if needed.

        Args:
            message (str, optional): 基础日志信息. Defaults to ''.
            request (HttpRequest, optional): 记录请求信息. Defaults to None.
            raise_exc (bool, optional): 是否抛出异常，不提供则根据debug模式决定
        '''
        if request is not None:
            message = self.format_request(request) + '\n' + message
        self.exception(message, stacklevel=2)
        if raise_exc is None:
            raise_exc = self.debug_mode
        if raise_exc:
            raise

    def _return_value(self, value: ReturnType[T]) -> T:
        return value() if callable(value) else value

    def secure_view(
        self, message: str = '', *,
        raise_exc: bool | None = False,
        fail_value: ReturnType[Any] = None,
        exc_type: ExceptType[Exception] = Exception
    ) -> Callable[[Callable[Concatenate[HttpRequest, P], T]],
                  Callable[Concatenate[HttpRequest, P], T]]:
        def decorator(view: Callable[Concatenate[HttpRequest, P], T]):
            @wraps(view)
            def wrapper(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> T:
                try:
                    return view(request, *args, **kwargs)
                except exc_type:
                    self.on_exception(message, request=request, raise_exc=raise_exc)
                    return self._return_value(fail_value)
            return wrapper
        return decorator

    def secure_func(
        self, message: str = '', *,
        raise_exc: bool | None = False,
        fail_value: ReturnType[Any] = None,
        exc_type: ExceptType[Exception] = Exception
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        def decorator(func: Callable[P, T]):
            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                try:
                    return func(*args, **kwargs)
                except exc_type:
                    arg_msg = ''
                    arg_msg += f'Function: {func.__module__}.{func.__qualname__}\n'
                    if args: arg_msg += f'Args: {args}\n'
                    if kwargs: arg_msg += f'Keywords: {kwargs}\n'
                    self.on_exception(arg_msg + message, raise_exc=raise_exc)
                    return self._return_value(fail_value)
            return wrapper
        return decorator
