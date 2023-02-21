from datetime import datetime


__all__ = [
    'mapping',
    'optional',
    'str_to_time',
]


def mapping(sequence, item):
    '''
    产生转换函数，该函数将会将一个序列中的每个元素转换成另一个类型

    Args:
        sequence (Type[Iterable]): 转换为的序列类型
        item (CastFunc): 转换函数

    Returns:
        Callable: 转换函数
    '''
    return lambda x: sequence(map(item, x))


def optional(func, default = None):
    def _func(x):
        if x is None:
            return default
        return func(x)
    return _func


DATETIME_FORMATS = [
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d %H',
    '%Y-%m-%d',
]


def str_to_time(time_string: str, *formats: str, optional: bool = False):
    '''
    将字符串转换为时间

    Args:
        time_string (str): 字符串格式的时间
        formats (str, optional): 允许的所有时间格式，如果不提供则使用默认的时间格式
        optional (bool, optional): 可选时，转换失败返回``None``. Defaults to False.

    Raises:
        ValueError: 转换失败时提供原始值

    Returns:
        datetime | None: 转换结果
    '''
    for format in formats or DATETIME_FORMATS:
        try:
            return datetime.strptime(time_string, format)
        except ValueError:
            pass
    if optional:
        return None
    raise ValueError(time_string)
