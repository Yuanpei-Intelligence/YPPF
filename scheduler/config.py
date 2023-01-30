from boot.config import Config, LazySetting


class __Config(Config):

    def __init__(self, dict_prefix: str = 'scheduler'):
        super().__init__(dict_prefix)
        self.rpc_port = LazySetting('rpc_port', default=6666)
        self.use_scheduler = LazySetting('use_scheduler', default=False)


scheduler_conf = __Config()
