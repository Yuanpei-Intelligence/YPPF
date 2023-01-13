'''
config.py

- 常量和设置
- 读取设置的api
- 可以全部导入而不必考虑命名空间冲突（仅包含get_setting和大写常量，详见__all__）
- `get_setting`和`get_config`的区别
    - 前者默认抛出异常，适合必要的设置，后者默认更加宽松，适合
    - 命名只是因为settings.py，不用太在意语义

@Date 2022-02-17
'''
# 对改动者：
# 本文件是最基础的依赖文件，应当只加入跨架构的必要常量，而不导入其他文件
# 与使用环境有关的内容应在对应文件中定义

from boot import base_get_setting, optional
from boot import (
    # settings相关常量
    DEBUG, MEDIA_URL, LOGIN_URL,
    # 全局的其它常量
    UNDERGROUND_URL, WECHAT_URL,
)
from utils.global_messages import (
    WRONG, SUCCEED,
)
from generic.models import User
from django.conf import settings

from utils.config import *

__all__ = [
    # 读取本地设置的函数
    'get_setting',
    # 全局设置的常量
    'DEBUG', 'MEDIA_URL', 'LOGIN_URL',
    'UNDERGROUND_URL', 'WECHAT_URL',
    # 全局消息的常量
    'WRONG', 'SUCCEED',
    # 本应用的常量
    'UTYPE_PER', 'UTYPE_ORG',
    # 本应用的CONFIG
    'CONFIG'
]

# 本应用的本地设置目录
PREFIX = ''

def get_setting(path: str='', trans_func=None, default=None,
               fuzzy_lookup=False, raise_exception=True):
    '''
    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    '''
    return base_get_setting(
        PREFIX + path, trans_func, default, fuzzy_lookup, raise_exception)

# 本应用的常量
UTYPE_PER = User.Type.PERSON.value
UTYPE_ORG = User.Type.ORG.value

class ProfileConfig(Config):
    def __init__(self) -> None:
        super().__init__()
        # 必要设置
        self.course: str = Setting('course')
        self.current_acadamic_year = Setting('semester_data/year', 
                trans_func=int)                               # 当前学年
        self.default_weather: dict = Setting('default_weather')
        self.hash_base: str = Setting('hash/base_hasher')
        self.hash_email: str = Setting('hash/email')
        self.hash_wechat: str = Setting('hash/wechat')
        self.help_message: dict = Setting('help_message')
        self.max_inform_rank: dict = Setting('max_inform_rank')
        self.msg: dict = Setting('msg')
        self.system_log: str = Setting('system_log')
        self.thresholds: dict = Setting('thresholds')
        self.url: dict = Setting('url')
        self.weather_api_key: str = Setting('weather_api_key')
        self.wechat_send: dict = Setting('config/wechat_send')
        self.yqp_oname: str = Setting('YQPoint_source_oname')

        # 可选设置，具有默认值
        self.course_type_name: str = LazySetting(
            'course/type_name', default='书院课程')
        self.least_record_hours: float = LazySetting(
            'course/valid_hours', float, default=8.0)
        self.wechat_app2url: dict = LazySetting(
            'config/wechat_send/app2url', dict, dict())
        self.wechat_receiver_set: set = LazySetting(
            'config/wechat_send/receivers', default=None, 
            trans_func=lambda x: set(map(str, x)) if x is not None else None)
        self.wechat_blacklist_set: set = LazySetting(
            'config/wechat_send/blacklist', default=set(),
            trans_func=lambda x: set(map(str, x)))
        self.wechat_unblock_apps: set = LazySetting(
            'config/wechat_send/unblock_apps', set, set())
        self.wechat_use_scheduler: bool = LazySetting(
            'config/wechat_send/use_scheduler', bool, default=True)
        self.yqp_activity_max: int|None = LazySetting(
            'thresholds/point/limit', optional(int), default=30)
        self.yqp_invalid_hour: float = LazySetting(
            'thresholds/point/invalid_hour', float, default=12)
        self.yqp_invalid_title: list = LazySetting(
            'thresholds/point/invalid_titles', default=[])
        self.yqp_per_hour: float = LazySetting(
            'thresholds/point/per_hour', float, default=10)
        self.yqp_per_feedback: int = LazySetting(
            'thresholds/point/per_feedback', int, default=10)

CONFIG = ProfileConfig()
