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
