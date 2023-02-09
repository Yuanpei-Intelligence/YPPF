'''
config.py

- 常量和设置
- 读取设置的api
- 可以全部导入而不必考虑命名空间冲突（仅包含和大写常量，详见__all__）

@Date 2022-02-17
'''
# 对改动者：
# 本文件是最基础的依赖文件，应当只加入跨架构的必要常量，而不导入其他文件
# 与使用环境有关的内容应在对应文件中定义

from boot.config import Config, LazySetting, GLOBAL_CONF
from boot import (
    # TODO: Change these
    # settings相关常量
    MEDIA_URL,
    # 全局的其它常量
    UNDERGROUND_URL, WECHAT_URL,
)
from utils.global_messages import (
    WRONG, SUCCEED,
)
from generic.models import User

__all__ = [
    # 全局设置的常量
    'MEDIA_URL',
    'UNDERGROUND_URL', 'WECHAT_URL',
    # 全局消息的常量
    'WRONG', 'SUCCEED',
    # 本应用的常量
    'UTYPE_PER', 'UTYPE_ORG',
    # 本应用的CONFIG
    'CONFIG', 'GLOBAL_CONF'
]


# 本应用的常量
UTYPE_PER = User.Type.PERSON.value
UTYPE_ORG = User.Type.ORG.value


class CourseConfig(Config):
    # str format: %Y-%m-%d %H:%M:%S
    yx_election_start = LazySetting('yx_election_start', type=str)
    yx_election_end = LazySetting('yx_election_end', type=str)
    btx_election_start = LazySetting('btx_election_start')
    btx_election_end = LazySetting('btx_election_end', type=str)
    publish_time = LazySetting('publish_time', type=str)

    def __init__(self, dict_prefix: str = 'course'):
        super().__init__(dict_prefix)


class ProfileConfig(Config):
    def __init__(self, dict_prefix: str = ''):
        super().__init__(dict_prefix)

    # email
    email_salt = LazySetting('email/salt', type=str)
    email_url = LazySetting('email/url', type=str)

    # Wechat
    hash_wechat = LazySetting('wechat/salt', type=str)
    wechat_app2url = LazySetting('wechat/app2url', default=dict())
    wechat_receiver_set = None
    wechat_blacklist_set = LazySetting(
        'wechat/blacklist', default=set(),
        trans_fn=lambda x: set(map(str, x)))
    wechat_unblock_apps = LazySetting(
        'wechat/unblock_apps', default=set(),
        trans_fn=lambda x: set(map(str, x)))
    wechat_use_scheduler: bool = True
    wechat_batch = LazySetting('wechat/batch', default=500)
    wechat_url = LazySetting('wechat/api_url', type=str)

    # Notification
    max_inform_rank = LazySetting('notification/max_inform_rank')
    help_message = LazySetting('help_message')

    # Course Info
    course_type_name = LazySetting('course/type_name', default='书院课程')
    least_record_hours = LazySetting('course/valid_hours', float, default=8.0)
    course = CourseConfig()

    # YQPoint
    # TODO: Change it
    yqp_oname = ''
    yqp_activity_max = LazySetting('YQPoint/activity/max', default=30)
    yqp_activity_per_hour = LazySetting(
        'YQPoint/activity/per_hour', float, default=10)
    yqp_per_feedback = LazySetting('YQPoint/feedback/per_accept', default=10)
    yqp_signin_points = LazySetting(
        'YQPoint/signin_points', default=[1, 2, 2, (2, 4), 2, 2, (5, 7)])


CONFIG = ProfileConfig()
