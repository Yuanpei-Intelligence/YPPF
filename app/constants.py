from django.http import HttpResponseRedirect

from boottest import local_dict
from django.conf import settings


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