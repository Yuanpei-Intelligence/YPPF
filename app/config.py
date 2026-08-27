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

from boot.config import ROOT_CONFIG, GLOBAL_CONFIG
from boot import (
    # TODO: Change these
    # settings相关常量
    MEDIA_URL,
)
from utils.config import Config, LazySetting
from utils.config.cast import mapping
from utils.hasher import MySHA256Hasher
from utils.global_messages import (
    WRONG, SUCCEED,
)
from generic.models import User

__all__ = [
    # 全局设置的常量
    'MEDIA_URL',
    # 全局消息的常量
    'WRONG', 'SUCCEED',
    # 本应用的常量
    'UTYPE_ORG',
    # 权限配置
    'PERMISSION_CONFIG',
    'PERMISSIONS_LIST',
    # 本应用的CONFIG
    'CONFIG', 'GLOBAL_CONFIG'
]


# 本应用的常量
UTYPE_ORG: str = User.Type.ORG.value

# 权限配置
PERMISSION_CONFIG = [
    {'key': 'select_course', 'name': '选课权限'},
    {'key': 'underground_appointment', 'name': '地下室权限'},
    {'key': 'gain_credit', 'name': '获得书院课学时权限'},
]

PERMISSIONS_LIST = [perm['key'] for perm in PERMISSION_CONFIG]


class ProfileConfig(Config):
    def __init__(self, source, dict_prefix = ''):
        super().__init__(source, dict_prefix)
        self.email = EmailConfig(self, 'email')
        self.course = CourseConfig(self, 'course')
        self.yqpoint = YQPointConfig(self, 'YQPoint')

    # Informations
    max_inform_rank = LazySetting('max_inform_rank', default={}, type=dict[str, int])
    help_message = LazySetting('help_messages', default={}, type=dict[str, str])
    weather_api_key = LazySetting('weather/api_key', type=str)
    password_reset_token_seconds = LazySetting(
        'password_reset/token_seconds', int, default=600)
    password_reset_token_attempts = LazySetting(
        'password_reset/token_attempts', int, default=5)
    password_reset_window_seconds = LazySetting(
        'password_reset/window_seconds', int, default=900)
    password_reset_lock_seconds = LazySetting(
        'password_reset/lock_seconds', int, default=900)
    password_reset_retention_seconds = LazySetting(
        'password_reset/retention_seconds', int, default=86400)
    password_reset_request_limits = LazySetting(
        'password_reset/request_limits',
        default={'account': 3, 'device': 5, 'ip': 10},
        type=dict[str, int],
    )
    password_reset_verify_limits = LazySetting(
        'password_reset/verify_limits',
        default={'account': 10, 'device': 10, 'ip': 10},
        type=dict[str, int],
    )


class YQPointConfig(Config):
    def __init__(self, source, dict_prefix = ''):
        super().__init__(source, dict_prefix)
        self.activity = YQPActivityConfig(self, 'activity')

    org_name = LazySetting('org_name', type=str)
    per_feedback = LazySetting('feedback/accept', default=10)
    signin_points = LazySetting(
        'signin_points', default=[1, 2, 2, (2, 4), 2, 2, (5, 7)])


class YQPActivityConfig(Config):
    invalid_hour = LazySetting('invalid_hour', float, default=6.0)
    max = LazySetting('max', type=(int, type(None)), default=30)
    per_hour = LazySetting('per_hour', float, default=10.0)


class EmailConfig(Config):
    salt = LazySetting('salt', type=str)
    hasher = LazySetting(salt, MySHA256Hasher, type=MySHA256Hasher)
    url = LazySetting('url', type=str)


class CourseConfig(Config):
    # str format: %Y-%m-%d %H:%M:%S
    yx_election_start = LazySetting('yx_election_start', type=str)
    yx_election_end = LazySetting('yx_election_end', type=str)
    btx_election_start = LazySetting('btx_election_start', type=str)
    btx_election_end = LazySetting('btx_election_end', type=str)
    publish_time = LazySetting('publish_time', type=str)

    # Course Info
    type_name = LazySetting('type_name', default='书院课程')
    least_record_hours = LazySetting('valid_hours', float, default=8.0)
    audit_teachers = LazySetting('auditors', mapping(list, str), type=list[str])


CONFIG = ProfileConfig(ROOT_CONFIG, '')
