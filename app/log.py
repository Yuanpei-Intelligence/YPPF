import logging

from record.log.logger import Logger
from utils.inspect import find_caller
from boot.config import GLOBAL_CONFIG
from extern.wechat import send_wechat


__all__ = [
    'logger',
]


class ProfileLogger(Logger):
    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1) -> None:
        file, caller, lineno = find_caller(stacklevel)
        source = f'{file}.{caller}'
        msg = str(msg)
        log_msg = source.ljust(30) + msg
        super()._log(level, log_msg, args, exc_info, extra, stack_info, stacklevel)
        if level >= logging.ERROR:
            self._send_wechat(f'错误位置：{source} {lineno}行\n' + msg, level)

    def _send_wechat(self, message: str, level: int = logging.ERROR):
        if not GLOBAL_CONFIG.debug_stuids:
            return
        send_wechat(
            GLOBAL_CONFIG.debug_stuids,
            '成长档案发生错误', message,
        )

    def secure_view(self, message: str = '出现意料之外的错误, 请联系管理员!',
                    url: str ='/welcome/'):
        from django.shortcuts import HttpResponseRedirect
        from utils.global_messages import wrong, message_url
        EXCEPT_REDIRECT = HttpResponseRedirect(message_url(wrong(message), url))
        return super().secure_view(message, fail_value=EXCEPT_REDIRECT)


logger = ProfileLogger.getLogger('profile')
