'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

依赖于app.API
'''
from typing import Callable, ParamSpec, Concatenate, cast, overload, Literal, TypeGuard
from functools import wraps

from django.db.models import QuerySet
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required

from Appointment.models import User, Participant
from Appointment.config import appointment_config as CONFIG
from utils.global_messages import wrong, succeed, message_url
from utils.http.dependency import HttpRequest, UserRequest, HttpResponse
from app import API

__all__ = [
    'get_participant',
    'is_org',
    'is_person',
    'get_name',
    'get_avatar',
    'get_member_ids', 'get_members',
    'get_auditor_ids',
    'identity_check',
]


@overload
def get_participant(user: User | str, update: bool = ...,
                    raise_except: Literal[False] = ...) -> Participant | None: ...
@overload
def get_participant(user: User | str, update: bool = ...,
                    raise_except: Literal[True] = ...) -> Participant: ...

def get_participant(user: User | str, update: bool = False,
                    raise_except: bool = False) -> Participant | None:
    '''通过User对象或学号获取对应的参与人对象

    Args:
    - update: 获取带更新锁的对象
    - raise_except: 失败时是否抛出异常，默认不抛出

    Returns:
    - participant: 满足participant.Sid=user, 不存在时返回`None`

    Raises:
    - DoesNotExist: 当`raise_except`为`True`时，如果不存在对应的参与人对象则抛出异常
    '''
    try:
        par_all: QuerySet[Participant] = Participant.objects.all()
        if update:
            par_all = par_all.select_for_update()

        if isinstance(user, str):
            return par_all.get(Sid_id=user)
        return par_all.get(Sid=user)
    except:
        if raise_except:
            raise
        return None


def _arg2user(participant: Participant | User) -> User:
    '''把范围内的参数转化为User对象'''
    if isinstance(participant, Participant):
        user = participant.Sid
    else:
        user = participant
    return user


# 获取用户身份
def is_valid(participant: Participant | User | AnonymousUser):
    '''返回participant对象是否是一个有效的用户'''
    user = _arg2user(participant)  # type: ignore
    return API.is_valid(user)

def is_org(participant: Participant | User):
    '''返回participant对象是否是组织'''
    user = _arg2user(participant)
    return API.is_org(user)

def is_person(participant: Participant | User):
    '''返回participant是否是个人'''
    user = _arg2user(participant)
    return API.is_person(user)


# 获取用户信息
def get_name(participant: Participant | User):
    '''返回participant(个人或组织)的名称'''
    user = _arg2user(participant)
    return API.get_display_name(user)


def get_avatar(participant: Participant | User):
    '''返回participant的头像'''
    user = _arg2user(participant)
    return API.get_avatar_url(user)


def get_member_ids(participant: Participant | User, noncurrent: bool = False):
    '''返回participant的成员id列表，个人返回空列表'''
    user = _arg2user(participant)
    return API.get_members(user, noncurrent=noncurrent)


def get_members(participant: Participant | User,
                noncurrent: bool = False) -> QuerySet[Participant]:
    '''返回participant的成员集合，Participant的QuerySet'''
    member_ids = get_member_ids(participant, noncurrent=noncurrent)
    return Participant.objects.filter(Sid__in=member_ids)


def get_auditor_ids(participant: Participant | User):
    '''返回participant的审核者id列表'''
    user = _arg2user(participant)
    return API.get_auditors(user)


# 用户验证、创建和更新
def _create_account(request: UserRequest, **values) -> Participant | None:
    '''
    根据请求信息创建账户, 根据创建结果返回生成的对象或者`None`, noexcept
    '''
    import pypinyin
    from django.db import transaction
    try:
        assert request.user.is_authenticated
        with transaction.atomic():
            given_name = get_name(request.user)

            # 设置首字母
            pinyin_list = pypinyin.pinyin(given_name, style=pypinyin.NORMAL)
            pinyin_init = ''.join([w[0][0] for w in pinyin_list])

            values.update(
                Sid=request.user,
                name=given_name,
                pinyin=pinyin_init,
            )
            values.setdefault('hidden', is_org(request.user))
            values.setdefault('longterm',
                is_org(request.user) and len(get_member_ids(request.user)) >= 10)

            account = Participant.objects.create(**values)
            return account
    except:
        return None


def _update_name(user: Participant | User | str) -> bool:
    import pypinyin
    from django.db import transaction

    if not isinstance(user, Participant):
        participant = get_participant(user)
        if participant is None:
            return False
    else:
        participant = user

    # 获取姓名, 只更新不同的
    given_name = get_name(participant)
    if given_name == participant.name:
        return False

    # 获取首字母
    pinyin_list = pypinyin.pinyin(given_name, style=pypinyin.NORMAL)
    pinyin_init = ''.join([w[0][0] for w in pinyin_list])

    # 更新数据库和session
    with transaction.atomic():
        participant = get_participant(participant.Sid, update=True, raise_except=True)
        assert participant is not None, '本来就存在的用户理应存在'
        participant.name = given_name
        participant.pinyin = pinyin_init
        participant.save()
    return True


P = ParamSpec('P')
AuthFunction = Callable[[Participant | None], bool]
ViewFunction = Callable[Concatenate[HttpRequest, P], HttpResponse]

def _authenticate(participant: Participant | None) -> TypeGuard[Participant]:
    return participant is not None

def identity_check(
    auth_func: AuthFunction = _authenticate,
    redirect_field_name: str = 'origin',
    allow_create: bool = True,
    update_name: bool = True,
) -> Callable[[ViewFunction[P]], ViewFunction[P]]:
    def decorator(view_function: ViewFunction[P]) -> ViewFunction[P]:
        @login_required(redirect_field_name=redirect_field_name)
        @wraps(view_function)
        def _wrapped_view(request: HttpRequest, *args: P.args, **kwargs: P.kwargs):

            _allow_create = allow_create and CONFIG.allow_newstu_appoint
            context = {}

            if not is_valid(request.user):
                _allow_create = False
            request = cast(UserRequest, request)

            cur_part = get_participant(request.user)

            if cur_part is not None and cur_part.name == '未命名' and update_name:
                _update_name(cur_part)

            if cur_part is None and _allow_create:
                cur_part = _create_account(request)
                if cur_part is not None:
                    succeed('账号不存在，已为您自动创建账号！', context)
                else:
                    warn_message = ('创建地下室账户失败，请联系管理员为您解决。'
                                    '在此之前，您可以查看实时人数。')
                    wrong(warn_message, context)

            if auth_func is not None and not auth_func(cur_part):
                # TODO: task 0 lzp, log it and notify admin
                if cur_part is not None:
                    warn_message = ('您访问了未授权的页面，如需访问请先登录。')
                    wrong(warn_message, context)
                elif not _allow_create:
                    warn_message = ('本页面暂不支持地下室账户创建，您可以先查看实时人数。')
                    wrong(warn_message, context)

            if context:
                return redirect(message_url(context, reverse('Appointment:index')))

            return view_function(request, *args, **kwargs)
        return _wrapped_view
    return decorator
