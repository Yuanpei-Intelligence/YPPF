import logging

from utils.log.logger import Logger
from utils.inspect import find_caller
from boot.config import GLOBAL_CONF
from extern.wechat import send_wechat


__all__ = [
    'logger',
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

    def secure_view(self, message: str = '出现意料之外的错误, 请联系管理员!',
                    url: str ='/welcome/'):
        from django.shortcuts import HttpResponseRedirect
        from utils.global_messages import wrong, message_url
        EXCEPT_REDIRECT = HttpResponseRedirect(message_url(wrong(message), url))
        return super().secure_view(message, fail_value=EXCEPT_REDIRECT)


logger = ProfileLogger.getLogger('profile')
