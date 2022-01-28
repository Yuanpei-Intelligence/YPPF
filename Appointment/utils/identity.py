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

__all__ = [
    'get_participant',
    'is_org',
    'is_person',
    'get_name',
    'get_avatar',
]


def get_participant(user: Union[User, str], update=False, raise_except=False):
    '''通过User对象或学号获取对应的参与人对象

    Args:
    - update: 获取带更新锁的对象
    - raise_except: 失败时是否抛出异常，默认不抛出

    Returns:
    - participant: 满足participant.Sid=user, 不存在时返回`None`
    '''
    try:
        # TODO: task 2 pht 修改模型字段后删除下行
        if isinstance(user, User): user = user.username
        if update:
            par_all = Participant.objects.select_for_update().all()
        else:
            par_all = Participant.objects.all()

        # TODO: task 2 pht 修改模型字段后增加一行如果是str，则改为__username获取
        return par_all.get(Sid=user)
    except:
        if raise_except:
            raise
        return None


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


def get_avatar(participant: Union[Participant, User]):
    '''返回participant的头像'''
    obj, user_type = _get_userinfo(_arg2user(participant))
    return get_user_ava(obj, user_type)
