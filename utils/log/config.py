import logging
from boot.config import Config, LazySetting

class LogConfig(Config):
    def __init__(self, dict_prefix: str = 'log'):
        super().__init__(dict_prefix)

    log_dir = LazySetting('dir', default='./logstore')
    format = LazySetting('format', default='%(asctime)s [%(levelname)s] %(message)s')
    level = LazySetting('level', default=logging.INFO, type=(int, str))
    stack_level = LazySetting('stack_level', default=8)


log_config = LogConfig()
