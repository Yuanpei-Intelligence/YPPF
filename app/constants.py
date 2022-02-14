'''
constants.py

- 常量和设置
- 读取设置的api
- 可以全部导入而不必考虑命名空间冲突（仅包含get_setting和大写常量，详见__all__）
- `get_setting`和`get_config`的区别
    - 前者默认抛出异常，适合必要的设置，后者默认更加宽松，适合
    - 命名只是因为settings.py，不用太在意语义

@Date 2022-01-17
'''
# 对改动者：
# 本文件是最基础的依赖文件，应当只加入跨架构的必要常量，而不导入其他文件
# 与使用环境有关的内容应在对应文件中定义

from boottest import base_get_setting
from django.conf import settings

__all__ = [
    'get_setting', 'get_config',
    'DEBUG', 'MEDIA_URL', 'LOGIN_URL',
    'WRONG', 'SUCCEED', 'SYSTEM_LOG',
    'YQP_ONAME', 'COURSE_TYPENAME',
]

PREFIX = ''

def get_setting(path: str='', default=None, trans_func=None,
               fuzzy_lookup=False, raise_exception=True):
    '''
    默认值更宽松的`get_setting`, 适合可选本地设置

    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    '''
    return base_get_setting(
        PREFIX + path, default, trans_func, fuzzy_lookup, raise_exception)


DEBUG = settings.DEBUG
MEDIA_URL = settings.MEDIA_URL
LOGIN_URL = settings.LOGIN_URL

WRONG, SUCCEED = 1, 2

YQP_ONAME = get_setting('YQPoint_source_oname')

SYSTEM_LOG = get_setting('system_log')

def get_config(path: str='', default=None, trans_func=None,
               fuzzy_lookup=False, raise_exception=False):
    '''
    默认值更宽松的`get_setting`, 适合可选本地设置

    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    '''
    return base_get_setting(
        PREFIX + path, default, trans_func, fuzzy_lookup, raise_exception)

COURSE_TYPENAME = get_config('course/type_name', '书院课程')
