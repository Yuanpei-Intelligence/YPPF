'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

可能依赖于app.utils
'''
from Appointment import global_info
from Appointment.models import Participant
from app.utils import (
    check_user_type,
    get_person_or_org,
    get_user_ava,
)
from typing import Union
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
    'identity_check',
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
        if update:
            par_all = Participant.objects.select_for_update().all()
        else:
            par_all = Participant.objects.all()

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
def _is_org_type(usertype):
    return usertype == 'Organization'

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


# 用户验证、创建和更新
def _create_account(request):
    '''
    根据请求信息创建账户, 根据创建结果返回生成的对象或者`None`, noexcept
    '''
    if not global_info.allow_newstu_appoint:
        return None

    import pypinyin
    from django.db import transaction
    try:
        assert request.user.is_authenticated
        with transaction.atomic():
            try:
                given_name = get_name(request.user)
            except:
                # TODO: task 1 pht 2022-1-26 将来仍无法读取信息应当报错
                from Appointment.utils.utils import operation_writer
                operation_writer(global_info.system_log,
                                f'创建未命名用户:学号为{request.user.username}',
                                'identity._create_account',
                                'Problem')
                given_name = '未命名'

            # 设置首字母
            pinyin_list = pypinyin.pinyin(given_name, style=pypinyin.NORMAL)
            pinyin_init = ''.join([w[0][0] for w in pinyin_list])

            # TODO: task 1 pht 2022-1-28 模型修改时需要调整
            account = Participant.objects.create(
                Sid=request.user.username,
                name=given_name,
                credit=3,
                pinyin=pinyin_init,
            )
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
    auth_func=lambda x: x is not None,
    redirect_field_name='origin',
    allow_create=True,
    update_name=True,
    ):

    def decorator(view_function):
        @login_required(redirect_field_name=redirect_field_name)
        @wraps(view_function)
        def _wrapped_view(request, *args, **kwargs):

            _allow_create = allow_create  # 作用域问题

            if request.user.is_superuser or request.user.is_staff:
                _allow_create = False

            cur_part = get_participant(request.user)

            if cur_part is not None and cur_part.name == '未命名' and update_name:
                _update_name(cur_part)
                
            if cur_part is None and _allow_create:
                cur_part = _create_account(request)

            if not auth_func(cur_part):
                # TODO: task 0 lzp, log it and notify admin
                if not cur_part:
                    request.session['warn_message'] = ('创建地下室账户失败，请联系管理员为您解决。'
                                                       '在此之前，您可以查看实时人数。')
                else:
                    request.session['warn_message'] = ('您访问了未授权的页面，如需访问请先登录。')
                return redirect(reverse('Appointment:index') + '?warn=1')

            return view_function(request, *args, **kwargs)
        return _wrapped_view
    return decorator
