from typing import TypeVar

T = TypeVar('T')

__all__ = [
    'deprecated',
    'need_refactor',
    'fix_me',
    'unstable',
    'script',
]


def deprecated(func: T) -> T:
    '''标记一个函数为过时的，不推荐使用，该代码随时可能被删除'''
    return func


def need_refactor(func: T) -> T:
    '''标记一个函数需要重构，通常由于代码在项目结构上不合理'''
    return func


def fix_me(func: T) -> T:
    '''标记一个函数为待修复的，存在低效或错误的实现，或代码风格不符合规范'''
    return func


def unstable(func: T) -> T:
    '''标记一个函数为不稳定的，即可能在未来的版本中被删除或改变'''
    return func


def script(func: T) -> T:
    '''标记一个函数为脚本性质，即在一个特殊环境中特化的代码，通常包含硬编码'''
    return func
