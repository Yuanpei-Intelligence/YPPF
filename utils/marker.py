from typing import TypeVar

T = TypeVar('T')


def need_refactor(fn: T) -> T:
    """
    标记一个函数需要重构，通常由于代码在项目结构上不合理
    """
    return fn


def fix_me(fn: T) -> T:
    """
    标记一个函数为待修复的，存在低效或错误的实现，或代码风格不符合规范
    """
    return fn


def unstable(fn: T) -> T:
    """
    标记一个函数为不稳定的，即可能在未来的版本中被删除或改变
    """
    return fn


def script(fn: T) -> T:
    """
    标记一个函数为脚本性质，即在一个特殊环境中特化的代码，通常包含硬编码
    """
    return fn
