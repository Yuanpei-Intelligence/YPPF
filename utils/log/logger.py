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
from typing import Callable, Any, cast, ParamSpec, Concatenate
from functools import wraps

from django.conf import settings

from boot.config import absolute_path
from utils.http.dependency import HttpRequest
from utils.log.config import log_config as CONFIG


__all__ = [
    'Logger',
]


_loggers: dict[str, 'Logger'] = dict()
P = ParamSpec('P')

class Logger(logging.Logger):
    @classmethod
    def getLogger(cls, name: str, setup: bool = True, root: bool = False):
        if name in _loggers:
            return cast(cls, _loggers[name])
        _logger_class  = logging.getLoggerClass()
        logging.setLoggerClass(cls)
        logger = cast(cls, logging.getLogger(name))
        logging.setLoggerClass(_logger_class)
        if setup:
            logger.setup(name, root=root)
        _loggers[name] = logger
        return logger

    def setup(self, name: str, handle: bool = True, root: bool = False) -> None:
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
        handler = logging.FileHandler(file_path, encoding='utf8', mode='a')
        handler.setFormatter(logging.Formatter(format or CONFIG.format))
        self.addHandler(handler)

    def set_debug_mode(self, debug: bool) -> None:
        self.debug_mode = debug

    def exception(self, msg: str, *args, stacklevel: int | None = None, **kwargs) -> None:
        if stacklevel is None:
            stacklevel = CONFIG.stack_level
        super().exception(msg, *args, stacklevel=stacklevel, **kwargs)

    @staticmethod
    def format_request(request: HttpRequest) -> str:
        ret = []
        ret.append('URL: ' + request.get_full_path())
        if request.user.is_authenticated:
            # Implicit Call: generic.models.User.__str__
            ret.append('User: ' + str(request.user))
        if request.method is not None:
            ret.append('Method: ' + request.method)
            if request.method.lower() == 'POST':
                try:
                    ret.append('Data: ' + json.dumps(request.POST.dict()))
                except:
                    ret.append('Failed to jsonify post data.')
        return '\n'.join(ret)

    def secure_view(self, message: str = '', ret = None):
        def decorator(view: Callable[Concatenate[HttpRequest, P], Any]):
            @wraps(view)
            def wrapper(request: HttpRequest, *args: P.args, **kwargs: P.kwargs):
                try:
                    return view(request, *args, **kwargs)
                except Exception:
                    if self.debug_mode: raise
                    self.exception(self.format_request(request) + message)
                    return ret
            return wrapper
        return decorator
