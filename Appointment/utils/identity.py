'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

依赖于app.API
'''
from Appointment import *
from Appointment.models import Participant
from app import API
from typing import Union, Callable
from django.http import HttpRequest
from django.db.models import QuerySet
from django.contrib.auth.models import User

from functools import wraps
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required

__all__ = [
    'get_participant',
    'is_org',
    'is_person',
    'get_name',
    'get_avatar',
    'get_member_ids', 'get_members',
    'identity_check',
]


# 兼容Django3.0及以下版本
if not hasattr(QuerySet, '__class_getitem__'):
    QuerySet.__class_getitem__ = classmethod(lambda cls, *args, **kwargs: cls)


def get_participant(user: Union[User, str], update=False, raise_except=False):
    '''通过User对象或学号获取对应的参与人对象

    Args:
    - update: 获取带更新锁的对象
    - raise_except: 失败时是否抛出异常，默认不抛出

    Returns:
    - participant: 满足participant.Sid=user, 不存在时返回`None`
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


def _arg2user(participant: Union[Participant, User]):
    '''把范围内的参数转化为User对象'''
    user = participant
    if isinstance(user, Participant):
        user = participant.Sid
    return user


# 获取用户身份
def is_valid(participant: Union[Participant, User]):
    '''返回participant对象是否是一个有效的用户'''
    user = _arg2user(participant)
    return API.is_org(user)

def is_org(participant: Union[Participant, User]):
    '''返回participant对象是否是组织'''
    user = _arg2user(participant)
    return API.is_org(user)

def is_person(participant: Union[Participant, User]):
    '''返回participant是否是个人'''
    user = _arg2user(participant)
    return API.is_person(user)


# 获取用户信息
def get_name(participant: Union[Participant, User]):
    '''返回participant(个人或组织)的名称'''
    user = _arg2user(participant)
    return API.get_display_name(user)


def get_avatar(participant: Union[Participant, User]):
    '''返回participant的头像'''
    user = _arg2user(participant)
    return API.get_avatar_url(user)


def get_member_ids(participant: Union[Participant, User], noncurrent=False):
    '''返回participant的成员id列表，个人返回空列表'''
    user = _arg2user(participant)
    return API.get_members(user, noncurrent=noncurrent)


def get_members(participant: Union[Participant, User],
                noncurrent=False) -> QuerySet[Participant]:
    '''返回participant的成员集合，Participant的QuerySet'''
    member_ids = get_member_ids(participant, noncurrent=noncurrent)
    return Participant.objects.filter(Sid__in=member_ids)


# 用户验证、创建和更新
def _create_account(request: HttpRequest, **values) -> Union[Participant, None]:
    '''
    根据请求信息创建账户, 根据创建结果返回生成的对象或者`None`, noexcept
    '''
    if not GLOBAL_INFO.allow_newstu_appoint:
        return None

    import pypinyin
    from django.db import transaction
    try:
        assert request.user.is_authenticated
        with transaction.atomic():
            try:
                given_name = get_name(request.user)
            except:
                if values.get('given_name') is None:
                    from Appointment.utils.utils import operation_writer
                    operation_writer(SYSTEM_LOG,
                                     f'找不到用户{request.user.username}的姓名',
                                     'identity._create_account', 'Error')

            # 设置首字母
            pinyin_list = pypinyin.pinyin(given_name, style=pypinyin.NORMAL)
            pinyin_init = ''.join([w[0][0] for w in pinyin_list])

            values.update(
                Sid=request.user,
                name=given_name,
                pinyin=pinyin_init,
            )
            values.setdefault('credit', 3)
            values.setdefault('hidden', is_org(request.user))

            account = Participant.objects.create(**values)
            return account
    except:
        return None


def _update_name(user: Union[Participant, User, str]):
    import pypinyin
    from django.db import transaction

    participant = user
    if not isinstance(user, Participant):
        participant = get_participant(user)
        if participant is None:
            return False

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
        participant.name = given_name
        participant.pinyin = pinyin_init
        participant.save()
    return True


def identity_check(
    auth_func: Callable[[Union[Participant, None]], bool]=lambda x: x is not None,
    redirect_field_name='origin',
    allow_create=False,
    update_name=True,
    ):

    def decorator(view_function: Callable):
        @login_required(redirect_field_name=redirect_field_name)
        @wraps(view_function)
        def _wrapped_view(request: HttpRequest, *args, **kwargs):

            _allow_create = allow_create  # 作用域问题
            context = {}

            if not is_valid(request.user):
                _allow_create = False

            cur_part = get_participant(request.user)

            if cur_part is not None and cur_part.name == '未命名' and update_name:
                _update_name(cur_part)

            if cur_part is None and _allow_create:
                cur_part = _create_account(request)
                if cur_part is not None:
                    my_messages.succeed('账号不存在，已为您自动创建账号！', context)

            if not auth_func(cur_part):
                # TODO: task 0 lzp, log it and notify admin
                if not cur_part:
                    warn_message = ('创建地下室账户失败，请联系管理员为您解决。'
                                    '在此之前，您可以查看实时人数。')
                    my_messages.wrong(warn_message, context)
                else:
                    warn_message = ('您访问了未授权的页面，如需访问请先登录。')
                    my_messages.wrong(warn_message, context)

            if context:
                return redirect(my_messages.message_url(
                                    context,
                                    reverse('Appointment:index')))

            return view_function(request, *args, **kwargs)
        return _wrapped_view
    return decorator
