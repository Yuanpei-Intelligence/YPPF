import pymysql
import json

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


def _load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict


local_dict = _load_local_json()


# settings是懒惰的，所以可以提前导入并读取正确的值，导入boot.settings则会错误
from django.conf import settings


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
        current_dir: dict = local_dict
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
UNDERGROUND_URL: str = base_get_setting('url/base_url')
WECHAT_URL: str = base_get_setting('url/wechat_url')
