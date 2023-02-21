import inspect
from typing import Callable

def find_caller(depth: int = 1) -> tuple[str, str, int]:
    '''
    获取调用者信息

    Args:
        depth (int, optional): 调用深度. Defaults to 1.

    Returns:
        tuple[str, str, int]: (文件名, 调用者名称, 调用处行数)
    '''
    frame = inspect.currentframe()
    for _ in range(depth):
        next_frame = frame.f_back
        if next_frame is None:
            break
        frame = next_frame
    code = frame.f_code
    return code.co_filename, code.co_name, frame.f_lineno


def wrapped_info(source: Callable | type):
    '''
    装饰器获取被装饰函数或类的信息

    Args:
        source (Callable | type): 被装饰函数或类
    
    Returns:
        tuple[str, str]: (文件名, 函数名)
    '''
    return source.__module__, source.__qualname__
