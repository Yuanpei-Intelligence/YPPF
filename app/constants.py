'''
constants.py

- 常量和设置
- 读取设置的api
- 可以全部导入而不必考虑命名空间冲突（仅包含get_setting和大写常量，详见__all__）

@Date 2022-01-17
'''
# 对改动者：
# 本文件是最基础的依赖文件，应当只加入跨架构的必要常量，而不导入其他文件
# 与使用环境有关的内容应在对应文件中定义

from boottest import local_dict
from django.conf import settings

__all__ = [
    'get_setting',
    'DEBUG', 'MEDIA_URL', 'LOGIN_URL',
    'WRONG', 'SUCCEED', 'SYSTEM_LOG',
    'YQPoint_oname',
]

DEBUG = settings.DEBUG
MEDIA_URL = settings.MEDIA_URL
LOGIN_URL = settings.LOGIN_URL
WRONG, SUCCEED = 1, 2

# 寻找其他本地设置
def get_setting(path: str='', default=None, trans_func=None,
                fuzzy_lookup=False, raise_exception=False):
    '''
    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    可选的trans_func标识了结果转换函数，可以是int str等
    也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    除非设置了raise_exception，否则不抛出异常
    '''
    try:
        paths = path.replace('\\', '/').split('/')
        current_dir = local_dict
        for query in paths:
            if fuzzy_lookup and not query:
                continue
            if current_dir.get(query, OSError) != OSError:
                current_dir = current_dir[query]
            elif fuzzy_lookup and current_dir.get(query.lower(), OSError) != OSError:
                current_dir = current_dir[query.lower()]
            elif fuzzy_lookup and current_dir.get(query.upper(), OSError) != OSError:
                current_dir = current_dir[query.upper()]
            else:
                raise OSError(f'setting not found: {query} in {path}')
        return current_dir if trans_func is None else trans_func(current_dir)
    except Exception as e:
        if raise_exception:
            raise
        if DEBUG:
            if default is None:
                print(f'{e}, but given no default')
            else:
                print(f'{e}, returning {default} instead')
        return default


YQPoint_oname = get_setting('YQPoint_source_oname', raise_exception=True)

SYSTEM_LOG = get_setting('system_log', raise_exception=True)