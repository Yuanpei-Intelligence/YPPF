'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

可能依赖于app.utils
'''
from Appointment.models import Participant
from app.utils import (
    check_user_type,
    get_person_or_org,
    get_user_ava,
)
from typing import Union
from django.contrib.auth.models import User
from app.models import *

__all__ = [
    'user2participant',
    'is_org',
    'is_person',
    'get_name',
    'get_avatar',
]


def user2participant(user, update=False):
    '''通过User对象获取对应的参与人对象, noexcept

    Args:
    - update: 获取带更新锁的对象, 暂不需要支持

    Returns:
    - participant: 满足participant.Sid=user, 不存在时返回`None`
    ''' 
    try:
        return Participant.objects.get(Sid=user)
    except:
        return None


def user2info(user: User):
    '''返回User对象对应的(object, type)二元组'''
    user_type = check_user_type(user)[1]
    obj = get_person_or_org(user, user_type)
    return obj, user_type


def _arg2user(participant: Union[Participant, User]):
    '''把范围内的参数转化为User对象'''
    user = participant
    if isinstance(user, Participant):
        user = participant.Sid
        # TODO: task 2 pht 修改模型字段后删除下行
        if isinstance(user, str): user = User.objects.get(username=user)
    return user


# 获取用户身份
def _is_org_type(usertype):
    return usertype == "Organization"

def is_org(participant: Union[Participant, User]):
    '''返回participant对象是否是组织'''
    user = _arg2user(participant)
    return _is_org_type(check_user_type(user)[1])

def is_person(participant: Union[Participant, User]):
    '''返回participant是否是个人'''
    return not is_org(participant)


# 获取用户信息
def _get_userinfo(user: User):
    '''返回User对象对应的(object, type)二元组'''
    user_type = check_user_type(user)[1]
    obj = get_person_or_org(user, user_type)
    return obj, user_type


def get_name(participant: Union[Participant, User]):
    '''返回participant(个人或组织)的名称'''
    obj, user_type = _get_userinfo(_arg2user(participant))
    if _is_org_type(user_type):
        return obj.oname
    else:
        return obj.name


def get_avatar(participant: Participant):
    '''返回participant的头像'''
    obj, user_type = _get_userinfo(_arg2user(participant))
    return get_user_ava(obj, user_type)






