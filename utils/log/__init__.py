from utils.log.logger import Logger

__all__ = [
    'get_logger',
    'err_capture',
]

get_logger = Logger.getLogger
err_capture = get_logger('error').secure_view  # TODO: deprecated
