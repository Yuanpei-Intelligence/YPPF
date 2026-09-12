from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = ['CONFIG', 'shihannet']


class BirthboardConfig(Config):
    # 页脚"联系我们"邮箱：点击通过 mailto 打开系统邮件客户端
    contact_email = LazySetting('contact_email', default='', type=str)
    # 制作名单：组织列表，每项 {"name": 组织名, "columns": [[姓名...], ...]}
    contributor_orgs = LazySetting('contributor_orgs', default=[], type=list)
    # 海报"模版下载"链接：投放页图片上传区展示的可点击下载地址
    template_download_url = LazySetting(
        'template_download_url',
        default='',
        type=str,
    )
    max_image_bytes = LazySetting(
        'max_image_bytes',
        default=10 * 1024 * 1024,
        type=int,
    )
    max_senders = LazySetting('max_senders', default=20, type=int)
    # 站内信/企业微信通知的发件人官方组织账号（Organization 类型）。
    # 用管理命令 `python manage.py ensure_birthboard_sender` 幂等创建；
    # 切换发件人只需改这里的 username（指向真实存在的组织账号）。
    sender_username = LazySetting(
        'sender_username',
        default='yppf_birthboard',
        type=str,
    )
    # 该发件人组织的显示名（Organization.oname / User.name），供创建命令使用。
    sender_name = LazySetting(
        'sender_name',
        default='生日灯牌',
        type=str,
    )
    # 投屏同步跨进程锁：持有超时（秒）与心跳间隔（秒）。持有者进程崩溃或超时后
    # 锁可被回收，避免 15 分钟重试任务长期咬死夜间投放。
    display_lock_timeout = LazySetting('display_lock_timeout', default=120, type=int)
    display_lock_heartbeat = LazySetting(
        'display_lock_heartbeat', default=30, type=int)
    # 「外屏找不到图」视为下架成功（目标已不在屏）；False 恢复旧语义（未匹配即失败）。
    not_found_as_success = LazySetting('not_found_as_success', default=True, type=bool)
    # pending 下架连续失败 N 次后停止自动重试（0 表示不限），需人工/命令重置。
    takedown_max_failures = LazySetting('takedown_max_failures', default=5, type=int)
    # 同一寿星同一天处于非终止态的投放记录数上限。
    max_per_receiver_per_date = LazySetting(
        'max_per_receiver_per_date', default=1, type=int)
    # 点赞限流：每用户每日次数。
    like_daily_limit = LazySetting('like_daily_limit', default=1, type=int)
    # 协议版本：升高后已签署用户需重新签署。
    protocol_version = LazySetting('protocol_version', default=1, type=int)
    # 整批回滚开关：True 保持旧语义（任一图失败则整批回滚）。
    batch_atomic = LazySetting('batch_atomic', default=False, type=bool)


CONFIG = BirthboardConfig(ROOT_CONFIG.get('birthboard', {}))


class ShihannetConfig(Config):
    """Playwright 登录外部投放屏（shihannet）的账号配置。"""
    username = LazySetting('username', default='', type=str)
    password = LazySetting('password', default='', type=str)
    url = LazySetting('url', default='', type=str)
    headless = LazySetting('headless', default=True, type=bool)
    slow_mo_ms = LazySetting('slow_mo_ms', default=0, type=int)
    network_retry_seconds = LazySetting(
        'network_retry_seconds',
        default=10,
        type=int,
    )


shihannet = ShihannetConfig(ROOT_CONFIG.get('shihannet', {}))
