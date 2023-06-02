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

from django.conf import settings

from boot.config import absolute_path
from utils.http.dependency import HttpRequest
from record.log.config import log_config as CONFIG
from utils.inspect import module_filepath
from utils.wrap import return_on_except, Listener, ExceptType


__all__ = [
    'Logger',
]


_loggers: dict[str, 'Logger'] = dict()
P = ParamSpec('P')
T = TypeVar('T')
R = TypeVar('R', bound=HttpRequest)
ReturnType = T | Callable[[], T]
ViewFunction = Callable[Concatenate[R, P], T]


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
        return '\n'.join(Logger._request_msgs(request))

    @classmethod
    def _request_msgs(cls, request: HttpRequest) -> list[str]:
        msgs = []
        msgs.append('URL: ' + request.get_full_path())
        if request.user.is_authenticated:
            msgs.append('User: ' + request.user.__str__())  # Traceable Call
        if request.method is not None:
            msgs.append('Method: ' + request.method)
            if request.method.lower() == 'POST':
                try:
                    msgs.append('Data: ' + json.dumps(request.POST.dict()))
                except:
                    msgs.append('Failed to jsonify post data.')
        return msgs

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
            msgs = self._request_msgs(request)
            if message:
                msgs.append(message)
            message = '\n'.join(msgs)
        self.exception(message, stacklevel=2)
        if raise_exc is None:
            raise_exc = self.debug_mode
        if raise_exc:
            raise

    def secure_view(
        self, message: str = '', *,
        raise_exc: bool | None = False,
        fail_value: ReturnType[Any] = None,
        exc_type: ExceptType[Exception] = Exception
    ) -> Callable[[ViewFunction[R, P, T]], ViewFunction[R, P, T]]:
        listener = self.listener(message, as_view=True, raise_exc=raise_exc)
        return return_on_except(fail_value, exc_type, listener)

    def secure_func(
        self, message: str = '', *,
        raise_exc: bool | None = False,
        fail_value: ReturnType[Any] = None,
        exc_type: ExceptType[Exception] = Exception
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        listener = self.listener(message, as_view=False, raise_exc=raise_exc)
        return return_on_except(fail_value, exc_type, listener)

    def _get_request_arg(self, request: HttpRequest, *args, **kwargs) -> HttpRequest:
        return request

    def _traceback_msgs(self, exc_info: Exception, func: Callable) -> list[str]:
        msgs = []
        msgs.append(f'Except {exc_info.__class__.__name__}: {exc_info}')
        msgs.append(f'Function: {func.__module__}.{func.__qualname__}')
        return msgs

    def _arg_msgs(self, args: tuple, kwargs: dict) -> list[str]:
        msgs = []
        if args: msgs.append(f'Args: {args}')
        if kwargs: msgs.append(f'Keywords: {kwargs}')
        return msgs

    def listener(self, message: str = '', *,
                 as_view: bool = False,
                 raise_exc: bool | None = None) -> Listener[Exception]:
        def _listener(exc: Exception, func: Callable, args: tuple, kwargs: dict):
            msgs = []
            if as_view:
                request = self._get_request_arg(*args, **kwargs)
                msgs.extend(self._request_msgs(request))
            else:
                msgs.extend(self._traceback_msgs(exc, func))
                msgs.extend(self._arg_msgs(args, kwargs))
            if message:
                msgs.append(message)
            self.on_exception('\n'.join(msgs), raise_exc=raise_exc)
        return _listener
