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
    inner_url_export,
)
from typing import Union
from django.contrib.auth.models import User
from django.shortcuts import redirect
from functools import wraps
import urllib.parse
import pypinyin
import os

__all__ = [
    'get_participant',
    'is_org',
    'is_person',
    'get_name',
    'get_avatar',
    'identity_check',
    'get_participant',
    'create_account'


]

class identity_check(object):

    def __init__(self, auth_func=None):
        self.auth_func = auth_func

    def __call__(self, view_function):
        @wraps(view_function)
        def _wrapped_view(request, *args, **kwargs):

            cur_part = get_participant(user=request.user.username)
            if not cur_part:
                cur_part = create_account(request)
            if not cur_part:
                # TODO: by lzp, log it and notify admin
                yppf_netloc = urllib.parse.urlparse(global_info.login_url).netloc
                request.session['alert_message'] = f"数据库中未找到您的详情信息，管理员会尽快处理此问题。"
                return redirect(inner_url_export(yppf_netloc, "/index/?alert=1"))
            elif not self.auth_func(cur_part):
                request.session['alert_message'] = f"您的账号访问了未授权页面。如有疑问，请联系管理员。"
                yppf_netloc = urllib.parse.urlparse(global_info.login_url).netloc 
                return redirect(os.path.join(yppf_netloc, "/index/?alert=1"))
            return view_function(request, *args, **kwargs)
        return _wrapped_view


def get_participant(user: Union[User, str], update=False, raise_except=False):
    '''通过User对象或学号获取对应的参与人对象

    Args:
    - update: 获取带更新锁的对象
    - raise_except: 失败时是否抛出异常，默认不抛出

    Returns:
    - participant: 满足participant.Sid=user, 不存在时返回`None`
    '''
    # LZP: 我建议把创建表项直接整合进这个函数
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


def create_account(request):
    '''
    根据请求信息创建账户, 根据创建结果返回生成的对象或者`None`, noexcept
    '''
    if not global_info.allow_newstu_appoint:
        return None

    try:
        with transaction.atomic():
            try:
                given_name = get_name(request.user)
            except:
                # TODO: task 1 pht 2022-1-26 将来仍无法读取信息应当报错
                operation_writer(global_info.system_log,
                                f"创建未命名用户:学号为{request.user.username}",
                                    "views.index",
                                    "Problem")
                given_name = "未命名"

            # 设置首字母
            pinyin_list = pypinyin.pinyin(given_name, style=pypinyin.NORMAL)
            pinyin_init = ''.join([w[0][0] for w in pinyin_list])

            # TODO: task 1 pht 2022-1-28 模型修改时需要调整
            account = Participant.objects.create(
                Sid=request.user.username,
                Sname=given_name,
                Scredit=3,
                pinyin=pinyin_init,
            )
            return account
    except:
        return None

# def identity_check(request):    # 判断用户是否是本人
#     '''目前的作用: 判断数据库有没有这个人'''
#     # 是否需要检测

#     if not global_info.account_auth:
#         return True

#     participant = get_participant(request.user)

#     if participant is None:
#         return False

#     return True