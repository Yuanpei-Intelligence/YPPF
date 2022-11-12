from typing import Union, List, Dict
from dataclasses import dataclass
import os
import logging
import fcntl


LogLevel = Union[int, str]


class LockedFileHandler(logging.Handler):

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path

    def handle(self, record: logging.LogRecord) -> bool:
        rv = self.filter(record)
        if rv:
            file_name = os.path.basename(self.file_path)
            file_dir = os.path.dirname(self.file_path)
            fd = os.open(os.path.join(file_dir, f'.{file_name}.lock'),
                         os.O_CREAT | os.O_RDWR | os.O_TRUNC)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                with open(self.file_path, 'a') as f:
                    f.write(self.format(record) + '\n')
            except:
                # TODO: Raise?
                pass
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        return rv


@dataclass
class FileLoggerFactory():
    """Used to generate two-layer loggers with file handler
    """
    log_root: str = ''
    log_level: LogLevel = 'INFO'
    log_dir: str = 'logs'
    log_format: str = '%(asctime)s [%(levelname)s] %(message)s'

    # In python 3.11, Self is introduced
    # def from_env(cls) -> Self:
    @classmethod
    def from_env(cls):
        return cls(
            log_root=os.environ.get('YPPF_ENV', ''),
            log_level=os.environ.get('YPPF_LOG_LEVEL', ''),
            log_dir=os.environ.get('YPPF_LOG_DIR', ''),
            log_format=os.environ.get('YPPF_LOG_FORMAT', '')
        )

    def config_logger(self, logger_name: str = '', log_level: LogLevel = 'INFO') -> logging.Logger:
        """Config logger with file handler

        :param log_root: used to create a child logger. \
            Defaults to '', which will get the root logger.
        :type logger_name: str, optional
        :param logger_name: used to create a child logger. \
            Defaults to '' or 'default'.
        :type logger_name: str, optional
        :param log_level: defaults to 'INFO'
        :type log_level: LogLevel, optional
        """
        logger_name = logger_name or 'default'
        logger = logging.getLogger(self.log_root).getChild(logger_name)
        for handle in logger.handlers:
            logger.removeHandler(handle)
        logger_file = os.path.join(
            self.log_dir, self.log_root, f'{logger_name}.log')
        handler = LockedFileHandler(os.path.join(
            self.log_dir, self.log_root, logger_file))
        handler.setFormatter(logging.Formatter(self.log_format))
        logger.addHandler(handler)
        logger.setLevel(log_level)
        return logger

logger_factory: FileLoggerFactory = FileLoggerFactory.from_env()
