'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

依赖于app.API
'''
from typing import Callable, ParamSpec, Concatenate, TypeVar, overload, Literal, TypeGuard
from functools import wraps

from django.db.models import QuerySet
from django.shortcuts import redirect
from django.urls import reverse
from utils.http.rewrite_auth import login_required
from utils.http.dependency import HttpRequest, UserRequest, HttpResponse

from Appointment.models import User, Participant
from Appointment.config import appointment_config as CONFIG
from utils.global_messages import wrong, succeed, message_url
from app import API

__all__ = [
    'get_participant',
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
# TODO: Create Account For all Person with Command
def _create_account(request: UserRequest, **values) -> Participant | None:
    '''
    根据请求信息创建账户, 根据创建结果返回生成的对象或者`None`, noexcept
    '''
    from django.db import transaction
    try:
        assert request.user.is_authenticated
        with transaction.atomic():
            values.update(Sid=request.user)
            values.setdefault('hidden', request.user.is_org())
            values.setdefault('longterm',
                request.user.is_org() and len(get_member_ids(request.user)) >= 10)
            account = Participant.objects.create(**values)
            return account
    except:
        return None


P = ParamSpec('P')
R = TypeVar('R', bound=HttpRequest)
AuthFunction = Callable[[Participant | None], bool]
ViewFunction = Callable[Concatenate[R, P], HttpResponse]

def _authenticate(participant: Participant | None) -> TypeGuard[Participant]:
    return participant is not None


def identity_check(
    auth_func: AuthFunction = _authenticate,
    redirect_field_name: str = 'origin',
    allow_create: bool = True
) -> Callable[[ViewFunction[UserRequest, P]], ViewFunction[HttpRequest, P]]:
    def decorator(view_function: ViewFunction[UserRequest, P]) -> ViewFunction[HttpRequest, P]:
        @login_required(redirect_field_name=redirect_field_name)
        @wraps(view_function)
        def _wrapped_view(request: UserRequest, *args: P.args, **kwargs: P.kwargs):

            _allow_create = allow_create and CONFIG.allow_newstu_appoint
            context = {}

            if not request.user.is_valid():
                _allow_create = False

            cur_part = get_participant(request.user)

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
