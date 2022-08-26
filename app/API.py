'''YPPF API
- 身份验证
- 获取用户信息

只依赖generic应用, constants, models, utils等基础文件

@Author pht
@Date 2022-08-17
'''
from generic.models import User
from app.models import Position, NaturalPerson
from app.utils import (
    check_user_type as __check_type,
    get_user_ava as __get_ava,
    get_classified_user as __get_obj,
    get_user_wallpaper as __get_wallpaper,
)
from app.constants import UTYPE_ORG, UTYPE_PER
from typing import List

__all__ = [
    'is_valid', 'is_org', 'is_person',
    'get_display_name', 'get_avatar_url', 'get_wallpaper_url',
    'get_members', 'get_auditors',
]


def is_valid(user: User) -> bool:
    '''返回用户是否是合法账户，不抛出异常'''
    return __check_type(user)[0]

def is_org(user: User) -> bool:
    '''返回用户是否是合法的组织账户，不抛出异常'''
    return __check_type(user)[1] == UTYPE_ORG

def is_person(user: User) -> bool:
    '''返回用户是否是合法的个人账户，不抛出异常'''
    return __check_type(user)[1] == UTYPE_PER


def get_display_name(valid_user: User) -> str:
    '''返回合法用户可展示的姓名'''
    user_type = __check_type(valid_user)[1]
    obj = __get_obj(valid_user, user_type)
    return obj.get_display_name()


def get_avatar_url(valid_user: User) -> str:
    '''返回合法用户头像的URL相对路径'''
    user_type = __check_type(valid_user)[1]
    obj = __get_obj(valid_user, user_type)
    return __get_ava(obj, user_type)


def get_wallpaper_url(valid_user: User) -> str:
    '''返回合法用户壁纸的URL相对路径'''
    user_type = __check_type(valid_user)[1]
    obj = __get_obj(valid_user, user_type)
    return __get_wallpaper(obj, user_type)


def get_members(valid_user: User, noncurrent=False) -> List[str]:
    '''返回合法用户的成员学号列表'''
    user_type = __check_type(valid_user)[1]
    if user_type != UTYPE_ORG:
        return []
    obj = __get_obj(valid_user, user_type)
    positions = Position.objects.activated(noncurrent=noncurrent).filter(org=obj)
    members = positions.values_list('person__person_id__username', flat=True)
    return list(members)


def get_auditors(valid_user: User) -> List[str]:
    '''返回合法用户的需要审核时的审核者学号列表'''
    user_type = __check_type(valid_user)[1]
    if user_type != UTYPE_ORG:
        return []
    obj = __get_obj(valid_user, user_type)
    auditors = []
    auditor: NaturalPerson = obj.otype.incharge
    if auditor is not None:
        auditors.append(auditor.get_user().get_username())
    return auditors
