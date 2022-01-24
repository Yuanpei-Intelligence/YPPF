import pymysql
import json

pymysql.install_as_MySQLdb()
pymysql.version_info = (1, 4, 6, "final", 0)


def load_local_json(path="./local_json.json"):
    with open(path, encoding="utf_8") as f:
        local_dict = json.load(f)
    return local_dict


local_dict = load_local_json()


# settings是懒惰的，所以可以提前导入并读取正确的值，导入boottest.settings则会错误
from django.conf import settings
# 寻找本地设置
def base_get_setting(path: str='', default=None, trans_func=None,
                fuzzy_lookup=False, raise_exception=True):
    '''
    提供/或\\分割的setting路径，尝试寻找对应路径的设置，失败时返回default
    - 如果某级目录未找到且设置了fuzzy_lookup，会依次尝试其小写、大写版本，并忽略空目录
    - 可选的trans_func标识了结果转换函数，可以是int str等
    - 也可以判断结果类型，在范围外抛出异常，从而得到设定的default值
    - 除非未设置raise_exception，否则不抛出异常
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
        if settings.DEBUG:
            if default is None:
                print(f'{e}, but given no default')
            else:
                print(f'{e}, returning {default} instead')
        return default
