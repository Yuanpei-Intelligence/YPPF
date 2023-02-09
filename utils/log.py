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
import sys
import logging
import json
from typing import Dict, Callable, Any
from functools import partial, wraps

from django.http import HttpRequest
from django.conf import settings

from boot.config import GLOBAL_CONF


# TODO: Get info from settings
# Format, loglevel,
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_LEVEL = logging.INFO
LOG_STACK_LEVEL = 8

_loggers: Dict[str, logging.Logger] = dict()


def get_logger(name: str) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]
    logger = logging.getLogger(name)
    for handle in logger.handlers:
        logger.removeHandler(handle)
    handler = logging.FileHandler(
        os.path.join(GLOBAL_CONF.log_dir, name + '.log'), encoding='utf8', mode='a')
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(LOG_LEVEL)
    _loggers[name] = logger
    logger.exception = partial(logger.exception, stacklevel=LOG_STACK_LEVEL)
    return logger


def _format_request(request: HttpRequest) -> str:
    ret = []
    ret.append('URL: ' + request.get_full_path())
    if request.user.is_authenticated:
        # Implicit Call: generic.models.User.__str__
        ret.append('User: ' + str(request.user))
    if request.method is not None:
        ret.append('Method: ' + request.method)
        if request.method.lower() == 'POST':
            try:
                ret.append('Data: ' + json.dumps(request.POST.dict))
            except:
                ret.append('Failed to jsonify post data.')
    return '\n'.join(ret)


def err_capture(logger: str | logging.Logger = 'err', message: str = '',
                ret: Any | Callable[[], Any] = None) -> Any:
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **argvs):
            try:
                return fn(*args, **argvs)
            except Exception:
                if settings.DEBUG:
                    raise
                # Get logger
                _logger = logger
                if isinstance(_logger, str):
                    _logger = get_logger(_logger)

                # Check first param, if find `HttpRequest`, format it and concat
                # with message
                _message = message
                if args and isinstance(args[0], HttpRequest):
                    _message = _format_request(args[0]) + _message
                _logger.exception(_message)

                # Make return value
                if isinstance(ret, Callable):
                    return ret()
                return ret
        return wrapper
    return decorator
