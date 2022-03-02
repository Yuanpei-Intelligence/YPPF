'''
constants.py

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

from boottest import base_get_setting
from boottest import (
    # settings相关常量
    DEBUG, MEDIA_URL, LOGIN_URL,
    # 全局的其它常量
    UNDERGROUND_URL, WECHAT_URL,
)
from boottest.global_messages import (
    WRONG, SUCCEED,
)
from django.conf import settings

__all__ = [
    # 读取本地设置的函数
    'get_setting', 'get_config',
    # 全局设置的常量
    'DEBUG', 'MEDIA_URL', 'LOGIN_URL',
    'UNDERGROUND_URL', 'WECHAT_URL',
    # 全局消息的常量
    'WRONG', 'SUCCEED',
    # Log记录的常量
    'SYSTEM_LOG',
    # 本应用的常量
    'UTYPE_PER', 'UTYPE_ORG',
    'CURRENT_ACADEMIC_YEAR',
    'YQP_ONAME',
    # 本应用可选设置的常量
    'COURSE_TYPENAME', 'LEAST_RECORD_HOURS',
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

def get_config(path: str='', trans_func=None, default=None,
               fuzzy_lookup=False, raise_exception=False):
    '''
    默认值更宽松的`get_setting`, 适合可选本地设置

    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    '''
    return base_get_setting(
        PREFIX + path, trans_func, default, fuzzy_lookup, raise_exception)


# Log记录的常量，未来可能从对应应用导入
SYSTEM_LOG: str = get_setting('system_log')

# 本应用的常量
UTYPE_PER = 'Person'
UTYPE_ORG = 'Organization'

# 本应用的必要设置
CURRENT_ACADEMIC_YEAR: int = get_setting('semester_data/year', int)
YQP_ONAME: str = get_setting('YQPoint_source_oname')

# 本应用的可选设置，每个都应该给出默认值
COURSE_TYPENAME: str = get_config('course/type_name', default='书院课程')
LEAST_RECORD_HOURS: float = get_config('course/valid_hours', float, default=8.0)
