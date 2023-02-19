from boot.config import Config, LazySetting
from utils.hasher import MySHA256Hasher


__all__ = ['wechat_config']


_to_set_str = lambda x: set(map(str, x))
_to_opt_set_str = lambda x: set(map(str, x)) if x is not None else None


class WechatConfig(Config):
    def __init__(self, dict_prefix: str = 'wechat'):
        super().__init__(dict_prefix)

    # 基础设置
    api_url = LazySetting('api_url', type=str)
    salt = LazySetting('salt', type=str)
    hasher = LazySetting(salt, MySHA256Hasher, type=MySHA256Hasher)

    # 接收范围设置
    # 可接收范围，None表示无限制
    receivers = LazySetting('receivers', _to_opt_set_str, None)
    # 黑名单
    blacklist = LazySetting('blacklist', _to_set_str, set())

    # 发送数量设置
    # 批量发送大小
    send_batch = LazySetting('batch', lambda x: min(1000, x), 500)

    # 发送设置
    # 订阅系统的发送量很大，不建议重发且重发通常无效
    retry: bool = False
    # 启用定时任务以启用其它功能
    use_scheduler = LazySetting('use_scheduler', default=True, type=bool)
    # 多线程异步发送
    multithread = LazySetting(use_scheduler)
    # 单次连接超时时间，响应时间一般为1s或12s（偶尔）
    timeout = LazySetting(multithread, lambda x: 15 if x else 5, type=(int, float))


wechat_config = WechatConfig()
