from boot.config import Config, LazySetting

class WechatConfig(Config):
    def __init__(self, dict_prefix: str = 'wechat'):
        super().__init__(dict_prefix)

    api_url = LazySetting('api_url', type=str)
    salt = LazySetting('salt', type=str)
    app2url = LazySetting('app2url', default=dict(), type=dict[str, str])

    _to_set_str = lambda x: set(map(str, x))
    _to_opt_set_str = lambda x: set(map(str, x)) if x is not None else None
    receivers = LazySetting('receivers', _to_opt_set_str, None)
    blacklist = LazySetting('blacklist', _to_set_str, set())

    send_limit = LazySetting('limit', lambda x: min(1000, x), 500)
    send_batch = LazySetting('batch', lambda x: min(1000, x), 500)

    retry: bool = False
    use_scheduler = LazySetting('use_scheduler', default=True, type=bool)

    unblock_apps = LazySetting('unblock_apps', _to_set_str, set())


wechat_config = WechatConfig()
