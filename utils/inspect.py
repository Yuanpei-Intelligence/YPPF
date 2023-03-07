import os
import inspect
from typing import Callable
from types import FrameType


def module_filepath(filepath: str):
    '''模块格式的路径，path.to.module.file'''
    try:
        filepath = os.path.relpath(filepath)
    except:
        pass
    filepath = filepath.replace('\\', '/').replace(':/', '.')
    filepath = filepath.replace('../', '?-.').replace('./', '')
    return filepath.replace('/', '.').removesuffix('.py')


def _get_filename(frame: FrameType) -> str:
    try:
        file_name = frame.f_globals['__name__']
    except:
        file_name = module_filepath(frame.f_code.co_filename)
    return file_name


def find_caller(depth: int = 1) -> tuple[str, str, int]:
    '''
    获取调用者信息

    Args:
        depth (int, optional): 调用深度. Defaults to 1.

    Returns:
        tuple[str, str, int]: (文件名, 调用者名称, 调用处行数)
    '''
    frame = inspect.currentframe()
    if frame is None:
        return 'unknown', 'unknown', 0
    while depth > 0:
        next_frame = frame.f_back
        if next_frame is None:
            break
        frame = next_frame
        if _get_filename(frame) != 'logging':
            depth -= 1
    code = frame.f_code
    file_name = _get_filename(frame)
    return file_name, code.co_name, frame.f_lineno


def wrapped_info(source: Callable | type):
    '''
    装饰器获取被装饰函数或类的信息

    Args:
        source (Callable | type): 被装饰函数或类
    
    Returns:
        tuple[str, str]: (文件名, 函数名)
    '''
    return source.__module__, source.__qualname__
