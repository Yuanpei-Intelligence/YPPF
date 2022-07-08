'''
global_messages.py

- 成功与错误提示信息的常量
- 读取、增添和传递信息
- 通过URL便捷传递信息
- 更容易读取请求和目录

@Author pht
@Date 2022-02-17
'''
# 类型信息提示
from typing import Union, TypedDict, Mapping, Callable, Sequence, Any

__all__ = [
    # 常量
    'WRONG', 'SUCCEED',
    'CODE_FIELD', 'MSG_FIELD', 'ALERT_FIELD',
    # 类型信息支持
    'MESSAGECONTEXT',
    # 生成全局消息
    'wrong', 'succeed', 'alert',
    # 读取全局消息
    'get_warning', 'get_alert', 'get_all',
    'get_global_message',
    # 转移全局消息
    'transfer_message_context',
    # 生成URL
    'append_query', 'message_url',
    # 读取其它目录类内容
    'read_key', 'read_content',
    'read_GET', 'read_POST',
]

# 常量
WRONG, SUCCEED = 1, 2
CODE_FIELD = 'warn_code'
MSG_FIELD = 'warn_message'
ALERT_FIELD = 'alert_message'

# 类型信息
MESSAGECONTEXT = TypedDict(
    'dict',
    warn_code=int, warn_message=str,
    alert_message=str,
)


# 生成全局消息
def wrong(message, context: dict=None) -> MESSAGECONTEXT:
    '''
    在错误的情况下返回的字典, message为错误信息
    如果提供了context，则向其中添加信息
    '''
    if context is None:
        context = dict()
    context[CODE_FIELD] = WRONG
    context[MSG_FIELD] = message
    return context


def succeed(message, context: dict=None) -> MESSAGECONTEXT:
    '''
    在成功的情况下返回的字典, message为提示信息
    如果提供了context，则向其中添加信息
    '''
    if context is None:
        context = dict()
    context[CODE_FIELD] = SUCCEED
    context[MSG_FIELD] = message
    return context


def alert(message, context: dict=None) -> MESSAGECONTEXT:
    if context is None:
        context = dict()
    context[ALERT_FIELD] = message
    return context


# 读取全局消息
def get_warning(source: Mapping, normalize=False):
    '''尝试以字典格式读取，失败时返回全None的元组，不抛出异常'''
    try:
        warn_code, warn_message = source[CODE_FIELD], source[MSG_FIELD]
        if normalize:
            warn_code, warn_message = int(warn_code), str(warn_message)
        assert warn_code in [WRONG, SUCCEED]
    except:
        warn_code, warn_message = None, None
    return warn_code, warn_message


def get_alert(source: Mapping, normalize=False):
    '''尝试以字典格式读取，失败时返回全None的元组，不抛出异常'''
    try:
        alert_message = source[ALERT_FIELD]
        if normalize:
            alert_message = str(alert_message)
    except:
        alert_message = None
    return alert_message


def get_all_message(source: Mapping, with_alert=False, normalize=False):
    '''尝试以字典格式读取，失败时返回全None的元组，不抛出异常'''
    warn_code, warn_message = get_warning(source, normalize)
    alert_message = get_alert(source, normalize) if with_alert else None
    return warn_code, warn_message, alert_message


def get_request_message(request, with_alert=False):
    '''
    返回包含所有请求参数的元组，不抛出异常
    按顺序分别返回(warn_code, warn_message, [alert_message, ])
    解析失败的部分返回None
    '''
    result = list(get_warning(request.GET, normalize=True))
    if with_alert:
        result.append(get_alert(request.GET, normalize=True))
    return tuple(result)


# 转移全局消息
def _move(context, warn_code, warn_message, alert_message=None):
    count = 0
    if warn_code is not None:
        context[CODE_FIELD], context[MSG_FIELD] = warn_code, warn_message
        count += 1
    if alert_message is not None:
        context[ALERT_FIELD] = alert_message
        count += 1
    return count

def transfer_message_context(source: dict, context=None,
                             with_alert=False, normalize=True) -> MESSAGECONTEXT:
    '''
    将来源中的全局消息导出到context
    如果未提供context，则创建一个新字典
    '''
    if context is None:
        context = dict()
    _move(context, *get_all_message(source, with_alert, normalize))
    return context


# 生成URL
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
        warn_code, warn_message = context[CODE_FIELD], context[MSG_FIELD]
    except:
        # 即使报错，也可能是因为其中一项不存在，排除对len有影响的dict和str
        if not isinstance(context, (str, dict)) and len(context) == 2:
            warn_code, warn_message = context
    # 如果不是以上的情况(即合法的字典或二元数组), 就报错吧, 别静默发生错误
    return append_query(url, warn_code=warn_code, warn_message=warn_message)


# 读取其它目录类内容
def read_key(
    content: Mapping, key: str,
    trans_func: Callable=None, default=None, raise_exception=False,
    ):
    '''
    读取键

    - key: 待读取的键值
    - default: 键不存在时的返回值, 默认为`None`
    - trans_func: 可选, 键存在时, 结果的类型转换函数, 如`int`, `str`
    - raise_exception: 键不存在时是否抛出异常, 默认不抛出
    '''
    try:
        result = content[key]
        return result if trans_func is None else trans_func(result)
    except Exception as e:
        if raise_exception:
            raise
        return default


def read_content(
    _content: Mapping,
    *_keys: str,
    _default=None, _trans_func: Callable=None, _raise: bool=False,
    _flat: bool=False,
    **_fields: Union[Callable, Any, Sequence],
    )-> Union[dict, tuple]:
    '''
    ### 读取目录

    #### 读取字段
    - _keys: 以默认设置读取的键值表
    - _fields: 以自定义格式读取的键，值以如下顺序解读（未解析部分以默认值补齐）:
        1. 如果可调用，被视为_trans_func参数
        2. 如果是字符类序列，被视为_default参数
        3. 如果可切片，至多三个起始元素分别对应_default,_trans_func和_raise参数
        4. 当元素不足3个且第一个参数可调用时，元素分别对应_trans_func和_raise参数
        5. 如果不可切片，被视为_default参数

    #### 设置
    - _default: 键不存在时的返回值, 默认为`None`
    - _trans_func: 可选, 键存在时, 结果的类型转换函数, 如`int`, `str`
    - _raise: 键不存在时是否抛出异常, 默认不抛出
    - _flat: 以值列表顺序输出结果，按照先keys后fields的顺序，默认以字典输出

    #### 样例代码
    ```
    c = dict(a=1, b=2, d='msg')
    # 读取可选字段
    >>> read_content(c, 'a', 'c', _trans_func=int)
    <<< {'a': 1, 'c': None}

    # 读取必要(类型匹配)字段
    >>> read_content(c, 'd', _raise=True)
    <<< {'d': 'msg'}

    # 同时读取必要和可选字段并检查/转化(可选为主)
    >>> read_content(
    ...     c, 'a', 'c', _default=0., _trans_func=float,
    ...     d=(str, True),
    ... )
    <<< {'a': 1.0, 'c': 0.0, 'd': 'msg'}
    >>> read_content(
    ...     c, 'a', 'c', _default=0., _trans_func=float,
    ...     d=(int, True), e=(None, None, True),
    ... )
    <<< ValueError: invalid literal for int() with base 10: 'msg'
    
    # 同时读取必要和可选字段并检查/转化(必要为主)
    >>> read_content(
    ...     c, 'a', _raise=True,
    ...     b=float, d=str,
    ...     c=('', str, False),
    ... )
    <<< {'a': 1, 'b': 2.0, 'd': 'msg', 'c': ''}
    # 输出为序列
    >>> read_content(
    ...     c, 'a', _raise=True,
    ...     b=float, d=str,
    ...     c=('', str, False),
    ... )
    <<< (1, 2.0, 'msg', '')
    ```
    '''
    result = [] if _flat else {}
    for key in _keys:
        value = read_key(_content, key, _trans_func, _default, _raise)
        result.append(value) if _flat else result.setdefault(key, value)
    for key, args in _fields.items():
        if callable(args):
            value = read_key(_content, key, args, _default, _raise)
        elif isinstance(args, (str, bytes)):
            value = read_key(_content, key, _trans_func, args, _raise)
        else:
            try:
                args = list(args[:3])
            except:
                args = [args]
            finally:
                if len(args) > 0 and len(args) < 3 and callable(args[0]):
                    args = [_default] + args
                args = args + [_default, _trans_func, _raise][len(args):]
            value = read_key(_content, key, args[1], args[0], args[2])
        result.append(value) if _flat else result.setdefault(key, value)
    return tuple(result) if _flat else result


def read_GET(request, key: str, trans_func=None, default=None, raise_exception=False):
    '''
    读取GET参数

    - key: 待读取的键值
    - default: 键不存在时的返回值, 默认为`None`
    - trans_func: 可选, 键存在时, 结果的类型转换函数, 如`int`, `str`
    - raise_exception: 键不存在时是否抛出异常, 默认不抛出
    - 调用者保证`request`是一个请求，否则行为未定义
    '''
    return read_key(request.GET, key, trans_func, default, raise_exception)


def read_POST(request, key: str, trans_func=None, default=None, raise_exception=False):
    '''
    读取POST参数

    - key: 待读取的键值
    - default: 键不存在时的返回值, 默认为`None`
    - trans_func: 可选, 键存在时, 结果的类型转换函数, 如`int`, `str`
    - raise_exception: 键不存在时是否抛出异常, 默认不抛出
    - 调用者保证`request`是一个请求，否则行为未定义
    '''
    return read_key(request.POST, key, trans_func, default, raise_exception)
