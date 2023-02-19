from boot.config import Config, LazySetting


__all__ = [
    'notification_wechat_config',
    'Levels',
    'Apps',
]


_to_set_str = lambda x: set(map(str, x))


class Levels:
    '''
    永远开放：DEFAULT INFO IMPORTANT
    常规上限是1000
    '''
    DEFAULT = None
    DEBUG = -1000
    # ERROR = -100
    INFO = 0
    # NORMAL = 200
    IMPORTANT = 500
    # FATAL = 1000
    # NOREJECT = 1001


class Apps:
    '''
    永远开放：DEFAULT NORMAL _*
    注意DEFAULT是指本系统设定的默认窗口
    NORMAL则是发送系统的默认窗口

    请先判断是否符合接受者条件，再判断消息类型
    如果符合接受者条件，请务必显式指定发送的应用，默认值不能判断接受者的范围
    一般建议外部推广也要显示指定应用
    '''
    DEFAULT = None
    # 以接受者
    TO_SUBSCRIBER = 'promote'   # 一切订阅内容都是推广
    TO_PARTICIPANT = 'message'  # 参与者是内部群体
    TO_MEMBER = 'message'       # 发送给成员的是内部消息
    # 以消息类型
    # 状态变更请以接受者为准
    NORMAL = 'default'          # 常规通知，默认窗口即可
    PROMOTION = 'promote'       # 推广消息当然是推广
    TERMINATE = 'message'       # 终止应该发给内部成员
    AUDIT = 'message'           # 审核是重要通知
    TRANSFER = 'message'        # 转账需要通知
    # 固有应用名
    _PROMOTE = 'promote'
    _MESSAGE = 'message'


class NotificationConfig(Config):
    # 发送应用设置
    # 应用名到域名的转换，可以是相对地址，也可以是绝对地址
    app2url = LazySetting('app2url', default=dict(), type=dict[str, str])
    # 不要求接收等级的应用
    unblock_apps = LazySetting('unblock_apps', _to_set_str, set())


notification_wechat_config = NotificationConfig('wechat')
