# 类型信息提示
from typing import Union
from app.constants import WRONG, SUCCEED

# 在错误的情况下返回的字典, message为错误信息
def wrong(message, context=None):
    '''
    在错误的情况下返回的字典, message为错误信息
    如果提供了context，则向其中添加信息
    '''
    if context is None:
        context = dict()
    context['warn_code'] = WRONG
    context['warn_message'] = message
    return context


def succeed(message, context=None):
    '''
    在成功的情况下返回的字典, message为提示信息
    如果提供了context，则向其中添加信息
    '''
    if context is None:
        context = dict()
    context['warn_code'] = SUCCEED
    context['warn_message'] = message
    return context


def append_query(url, *, _query: str='', **querys):
    '''
    在URL末尾附加GET参数

    关键字参数
    - _query: str, 直接用于拼接的字符串

    说明
    - 已包含GET参数的URL将会以`&`连接
    - _query开头无需包含`?`或`&`
    - 基于字符串(`str`)拼接，URL不能包含段参数`#`
    '''
    concat = '&' if '?' in url else '?'
    new_querys = []
    if _query:
        new_querys.append(_query.lstrip('?&'))
    for k, v in querys.items():
        new_querys.append(f'{k}={v}')
    return url + concat + '&'.join(new_querys)


def message_url(context: Union[dict, list], url: str='/welcome/')-> str:
    '''
    提供要发送的信息体和原始URL，返回带提示信息的URL
    - context: 包含`warn_code`和`warn_message`的字典或者二元数组
    - url: str, 可以包含GET参数
    '''
    try:
        warn_code, warn_message = context['warn_code'], context['warn_message']
    except:
        # 即使报错，也可能是因为其中一项不存在，排除对len有影响的dict和str
        if not isinstance(context, (str, dict)) and len(context) == 2:
            warn_code, warn_message = context
    # 如果不是以上的情况(即合法的字典或二元数组), 就报错吧, 别静默发生错误
    append_msg = f'warn_code={warn_code}&warn_message={warn_message}'
    return append_query(url, warn_code=warn_code, warn_message=warn_message)


def get_global_message(request):
    '''
    解析失败时返回None, 
    成功时返回(warn_code, warn_message)
    '''
    try:
        warn_code = int(request.GET['warn_code'])
        warn_message = str(request.GET['warn_message'])
        assert warn_code in [WRONG, SUCCEED]
        return warn_code, warn_message
    except:
        return None