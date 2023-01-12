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

from typing import Dict
import os
import logging
from functools import partial


# TODO: Get info from settings
# LogDir, Format, loglevel,
LOG_DIR = '/var/log'
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
        os.path.join(LOG_DIR, name + '.log'))
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(LOG_LEVEL)
    _loggers[name] = logger
    logger.exception = partial(logger.exception, stacklevel=LOG_STACK_LEVEL)
    return logger
