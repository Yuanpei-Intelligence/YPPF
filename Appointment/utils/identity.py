'''
文件名: identity.py
负责人: pht

包含与身份有关的工具函数

可能依赖于app.utils
'''
from Appointment.models import Participant
from django.core.exceptions import ObjectDoesNotExist
from app.utils import (
    get_person_or_org,
    check_user_type,
)
from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
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
    try:
        return Participant.objects.get(Sid=user)
    except ObjectDoesNotExist:
        return None


def user2info(user):
    '''返回User对象对应的(type, object)二元组'''
    user_type = check_user_type(user)[1]
    obj = get_person_or_org(user, user_type)
    return user_type, obj


def participant2obj(participant):
    '''返回participant对应的object，不存在时返回None'''
    try:
        return NaturalPerson.objects.get(person_id=participant.Sid)
    except ObjectDoesNotExist:
        return None


def request2obj(request):
    '''返回request对应的object'''
    username = request.user.get_username()
    try:
        obj = NaturalPerson.objects.get(person_id_username=username)
    except ObjectDoesNotExist:
        obj = Organization.objects.get(organization_id_username=username)
    return obj


def request2participant(request):
    '''返回request对应的participant'''
    username = request.user.get_username()
    obj = NaturalPerson.objects.get(person_id_username=username)
    return Participant.objects.get(Sid=obj.person_id)