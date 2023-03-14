import logging
from utils.config import Config, LazySetting
from boot.config import ROOT_CONFIG

class LogConfig(Config):
    log_dir = LazySetting('dir', default='./logstore')
    format = LazySetting('format', default='{asctime} [{levelname}] {message}')
    level = LazySetting('level', default=logging.INFO, type=(int, str))
    stack_level = LazySetting('stack_level', default=8)


log_config = LogConfig(ROOT_CONFIG, 'log')
