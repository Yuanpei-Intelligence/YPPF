import logging

from utils.log.logger import Logger
from utils.inspect import find_caller
from boot.config import GLOBAL_CONF
from extern.wechat import send_wechat


__all__ = [
    'logger',
    'except_captured',
]


class ProfileLogger(Logger):
    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1) -> None:
        file, caller, _ = find_caller(depth=3)
        source = f"{file}.{caller}"
        msg = source.ljust(30) + str(msg)
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)
        if level >= logging.ERROR:
            self._send_wechat(msg, level)

    def _send_wechat(self, message: str, level: int = logging.ERROR):
        send_wechat(
            GLOBAL_CONF.debug_stuids,
            '成长档案发生错误', message,
        )


logger = ProfileLogger.getLogger('profile')

def except_captured(return_value=None, except_type=Exception):
    """
    Decorator that captures exception and log, raise or 
    return specific value if `return_value` is assigned.
    """

    return logger.secure_view(fail_value=return_value, exc_type=except_type)
