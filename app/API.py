'''YPPF API
- 身份验证
- 获取用户信息

只依赖generic应用, constants, models, utils等基础文件

@Author pht
@Date 2022-08-17
'''
from generic.models import User
from utils.models.query import qsvlist
from app.models import (
    NaturalPerson as Person,
    Position as Position,
)
from app.utils import (
    get_user_ava as __get_ava,
    get_classified_user as __get_obj,
    get_user_wallpaper as __get_wallpaper,
)

__all__ = [
    'get_display_name', 'get_avatar_url', 'get_wallpaper_url',
    'get_members', 'get_auditors',
]


def get_display_name(valid_user: User) -> str:
    '''返回合法用户可展示的姓名'''
    return __get_obj(valid_user).get_display_name()


def get_avatar_url(valid_user: User) -> str:
    '''返回合法用户头像的URL相对路径'''
    return __get_ava(__get_obj(valid_user))


def get_wallpaper_url(valid_user: User) -> str:
    '''返回合法用户壁纸的URL相对路径'''
    return __get_wallpaper(__get_obj(valid_user))


def get_members(valid_user: User, noncurrent: bool = False) -> list[str]:
    '''返回合法用户的成员学号列表'''
    if not valid_user.is_org():
        return []
    obj = __get_obj(valid_user)
    positions = Position.objects.activated(noncurrent=noncurrent).filter(org=obj)
    return qsvlist(positions, Position.person, Person.person_id, User.username)


def get_auditors(valid_user: User) -> list[str]:
    '''返回合法用户的需要审核时的审核者学号列表'''
    if not valid_user.is_org():
        return []
    obj = __get_obj(valid_user)
    auditors = []
    auditor = obj.otype.incharge
    if auditor is not None:
        auditors.append(auditor.get_user().get_username())
    return auditors
