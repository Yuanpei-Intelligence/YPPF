'''
这个文件中的很多内容实际上已经不需要了，但是还有一些依赖没改完。
'''

import pymysql
import json

from boot.config import CONFIG

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


def _load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict


local_dict = _load_local_json()
local_dict_template = _load_local_json("./local_json_template.json")


# settings是懒惰的，所以可以提前导入并读取正确的值，导入boot.settings则会错误
from django.conf import settings

def _query_setting(paths, dic=local_dict, fuzzy_lookup=False):
    current_dir: dict = dic
    if len(paths) and paths[0] == '':
        paths = paths[1:]
    for query in paths:
        if fuzzy_lookup and not query:
            continue
        if query in current_dir.keys():
            current_dir = current_dir[query]
        elif fuzzy_lookup and query.lower() in current_dir.keys():
            current_dir = current_dir[query.lower()]
        elif fuzzy_lookup and query.upper() in current_dir.keys():
            current_dir = current_dir[query.upper()]
        else:
            raise ValueError(f'setting not found: {query} in {path}')
    return current_dir

# 寻找本地设置
def base_get_setting(path: str='', trans_func=None, default=None,
                     fuzzy_lookup=False, raise_exception=True):
    '''
    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    - 除非未设置raise_exception，否则不抛出异常
    '''
    try:
        paths = path.replace('\\', '/').strip('/').split('/')
        current_dir = _query_setting(paths, local_dict, fuzzy_lookup)
        return current_dir if trans_func is None else trans_func(current_dir)
    except Exception as e:
        if raise_exception:
            raise
        try:
            # settings正在加载时，DEBUG全局变量未定义，需要使用settings.DEBUG
            debug = settings.DEBUG
        except:
            debug = True
        if debug:
            if default is None:
                print(f'{e}, but given no default')
            else:
                print(f'{e}, returning {default} instead')
        return default

# 如果本地设置中找不到，到local_json_template中寻找默认设置
def get_setting_with_default(path: str='', trans_func=None):
    try:
        paths = path.replace('\\', '/').strip('/').split('/')
        current_dir = _query_setting(paths, local_dict)
        return current_dir if trans_func is None else trans_func(current_dir)
    except Exception as e:
        current_dir = _query_setting(paths, local_dict_template)
        # 上面这步按理来说不该出错
        print(f'{e}, returning default value instead: {current_dir}')
        return current_dir if trans_func is None else trans_func(current_dir)


def optional(type):
    '''产生用于可选设置的转换函数，None被直接返回'''
    def _trans_func(value):
        if value is None:
            return None
        return type(value)
    return _trans_func


# 全局设置
# 加载settings.xxx时会加载文件
DEBUG: bool = settings.DEBUG
MEDIA_URL: str = settings.MEDIA_URL
LOGIN_URL: str = settings.LOGIN_URL

# 全局设置变量
UNDERGROUND_URL: str = CONFIG.underground_url
WECHAT_URL: str = CONFIG.wechat_url
