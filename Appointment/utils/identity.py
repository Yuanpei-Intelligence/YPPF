'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

可能依赖于app.utils
'''
from app.utils import (
)

__all__ = [
]


def user2participant(user, update=False):
    '''通过User对象获取对应的参与人对象, noexcept

    Args:
    - update: 获取带更新锁的对象, 暂不需要支持

    Returns:
    - participant: 满足participant.Sid=user, 不存在时返回`None`
    '''
    raise NotImplementedError
