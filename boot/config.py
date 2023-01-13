import os
import logging

from utils.config import *

__all__ = ['CONFIG']

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class BootConfig(Config):
    def __init__(self) -> None:
        super().__init__()
        self.db_host: str = Setting('database/HOST', default='127.0.0.1')
        self.db_name: str = Setting('database/NAME')
        self.db_password: str = Setting('database/PASSWORD')
        self.db_user: str = Setting('database/USER')
        self.env: str = Setting("YPPF_ENV", default="")
        self.inner_port: int = Setting("YPPF_INNER_PORT", default=80)
        self.login_url: str = Setting('url/login_url')
        self.log_dir: str = Setting("YPPF_LOG_DIR", default=BASE_DIR)
        self.log_level = Setting("YPPF_LOG_DEBUG", default="",
            trans_func=lambda x: logging.DEBUG if x else logging.INFO)
        self.underground_url: str = Setting('url/base_url')
        self.scheduler_port: int = Setting("YPPF_SCHEDULER_PORT", default=6666)
        self.static_dir: str = Setting("YPPF_STATIC_DIR", default=BASE_DIR)
        self.tmp_dir: str = Setting("YPPF_TMP_DIR", default=BASE_DIR)
        self.wechat_url: str = Setting('url/wechat_url')
        self.init_setting()

CONFIG = BootConfig()
