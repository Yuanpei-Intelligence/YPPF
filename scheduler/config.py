from boot.config import Config, LazySetting


class __Config(Config):

    def __init__(self, dict_prefix: str = 'scheduler'):
        super().__init__(dict_prefix)
        self.rpc_port: int = LazySetting('rpc_port')        # type: ignore
        self.use_scheduler: bool = LazySetting(
            'use_scheduler', default=False)  # type: ignore


scheduler_conf = __Config()
