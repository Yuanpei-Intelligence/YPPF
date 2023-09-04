from datetime import datetime, timedelta
from typing import Iterable, Literal

from django.db import transaction

from Appointment.config import appointment_config as CONFIG
from Appointment.models import Participant, Room, Appoint
from Appointment.utils.utils import get_conflict_appoints
from Appointment.utils.log import logger, get_user_logger
from Appointment.appoint.jobs import set_scheduler, cancel_scheduler
from Appointment.extern.wechat import MessageType, notify_appoint
from Appointment.extern.jobs import set_appoint_reminder
from utils.wrap import return_on_except, stringify_to
from achievement.unlock_api import unlock_achievement
from generic.models import User


__all__ = [
    'create_require_num',
    'create_appoint',
    'cancel_appoint',
]


def _notify_create(appoint: Appoint, students_id: list[str] | None = None) -> bool:
    '''提醒有新预约，根据时间和预约类型决定如何发送'''
    if appoint.Atype == Appoint.Type.TEMPORARY:
        notify_appoint(appoint, MessageType.TEMPORARY, students_id=students_id)
        return True
    if datetime.now() >= appoint.Astart:
        logger.warning(f'预约{appoint.Aid}尝试发送给微信时已经开始，且并非临时预约')
        return False
    if datetime.now() <= appoint.Astart - timedelta(minutes=15):
        notify_appoint(appoint, MessageType.NEW, students_id=students_id)
    else:
        notify_appoint(appoint, MessageType.NEW_INCOMING,
                       students_id=students_id)
    return True


def create_require_num(room: Room, type: Appoint.Type) -> int:
    '''创建预约的最小人数要求'''
    create_min: int = room.Rmin
    if type == Appoint.Type.TODAY:
        create_min = min(create_min, CONFIG.today_min)
    if type == Appoint.Type.TEMPORARY:
        create_min = min(create_min, CONFIG.temporary_min)
    if type == Appoint.Type.INTERVIEW:
        create_min = min(create_min, 1)
    return create_min


def _success(appoint: Appoint):
    return appoint, ''


def _error(msg: str):
    return None, msg


def _check_credit(appointer: Participant):
    appointer = Participant.objects.select_for_update().get(pk=appointer.pk)
    assert appointer.credit > 0, '信用分不足，本月无法发起预约！'


def _check_appoint_time(start: datetime, finish: datetime):
    assert start <= finish, '开始时间不能晚于结束时间！'
    assert finish > datetime.now(), '预约时间不能早于当前时间！'


def _check_room_valid(room: Room | None):
    assert room is not None, '预约的房间不存在！'
    assert room.Rstatus == Room.Status.PERMITTED, '预约的房间不可用！'


def _check_create_num(room: Room, type: Appoint.Type, inner: int, outer: int):
    create_min = create_require_num(room, type)
    assert inner + outer >= create_min, f'预约人数不足{create_min}人！'
    # TODO: 内部人数可能不是通用检查条件
    assert 2 * inner >= create_min, '院内使用人数需要达到房间最小人数的一半！'


def _check_num_constraint(room: Room, type: Appoint.Type, inner: int, outer: int):
    # TODO: 移除硬编码
    if room.Rid.startswith('R3'):
        assert inner == 1 and outer == 0, '俄文楼元创空间仅支持单人预约！'
    if type == Appoint.Type.TEMPORARY:
        assert inner == 1 and outer == 0, '临时预约仅支持单人预约！'
    if type == Appoint.Type.INTERVIEW:
        assert inner == 1 and outer == 0, '面试仅支持单人预约！'


def _check_conflict(appoint: Appoint):
    conflict_appoints = get_conflict_appoints(appoint, lock=True)
    assert len(conflict_appoints) == 0, '预约时间段与已有预约冲突！'


def _attend_require_num(room: Room, type: Appoint.Type, start: datetime, finish: datetime) -> int:
    '''实际监控检查要求的人数'''
    require_num = create_require_num(room, type)
    if require_num <= CONFIG.today_min:
        return require_num
    # 107b的监控不太靠谱，正下方看不到
    if room.Rid == "B107B":
        require_num -= 2
    # 地下室关灯导致判定不清晰，晚上更严重
    elif room.Rid == "B217":
        require_num -= 2 if start.hour >= 20 else 1
    # 最多减到当日人数要求
    return max(require_num, CONFIG.today_min)


@logger.secure_func('创建预约失败', fail_value=_error('添加预约失败!请与管理员联系!'))
@transaction.atomic
@return_on_except(stringify_to(_error), AssertionError, merge_type=True)
def create_appoint(
    appointer: Participant,
    room: Room,
    start: datetime, finish: datetime,
    usage: str,
    students: Iterable[Participant] | None = None,
    announce: str = '',
    outer_num: int = 0,
    *,
    type: Appoint.Type = Appoint.Type.NORMAL,
    notify: bool = True,
) -> tuple[Appoint, Literal['']]:
    '''创建预约

    创建预约并设置所有可以独立执行的功能，如状态切换等，无需额外调用。
    预约信息必须逻辑上正确，且满足预约的通用条件，如房间可用、时间有序、人数合法等。
    发起者必须有足够的信用分，否则无法创建预约。

    Args:
        appointer(Participant): 发起人
        room(Room): 预约房间
        start(datetime): 预约开始时间
        finish(datetime): 预约结束时间
        usage(str): 预约用途
        students(Iterable[Participant], optional): 预约参与人，发起人默认参与
        announce(str, optional): 预约内部公告
        outer_num(int, optional): 预约外部人数

    Keyword Args
        type(Appoint.Type): 预约类型，默认为普通预约
        notify(bool): 是否发送通知，默认为发送

    Returns:
        tuple[Appoint, Literal['']]: 预约对象和空错误信息
        tuple[None, str]: 错误信息
    '''

    _check_room_valid(room)
    _check_appoint_time(start, finish)

    if students is None:
        students = []
    students = list(students)
    if appointer not in students:
        students.append(appointer)
    inner_num = len(students)

    _check_create_num(room, type, inner_num, outer_num)
    _check_num_constraint(room, type, inner_num, outer_num)

    _check_credit(appointer)
    appoint = Appoint(
        major_student=appointer, Room=room,
        Astart=start, Afinish=finish,
        Ausage=usage, Aannouncement=announce,
        Anon_yp_num=outer_num, Ayp_num=inner_num,
        Aneed_num=_attend_require_num(room, type, start, finish),
        Atype=type,
    )
    _check_conflict(appoint)

    appoint.save()
    appoint.students_manager.set(students)

    set_scheduler(appoint)
    if notify:
        _notify_create(appoint)
    set_appoint_reminder(appoint)

    get_user_logger(appointer).info(f"发起预约，预约号{appoint.pk}")

    # 如果预约者是个人，解锁成就-完成地下室预约 该部分尚未测试
    user = appointer.Sid
    if user.is_person():
        unlock_achievement(user, '完成地下室预约')

    return _success(appoint)


@transaction.atomic
def cancel_appoint(appoint: Appoint, record: bool = True, lock: bool = True):
    '''原子化取消预约，不加锁时使用原对象'''
    if lock:
        appoint = Appoint.objects.select_for_update().get(pk=appoint.pk)
    appoint.Astatus = Appoint.Status.CANCELED
    appoint.save()
    cancel_scheduler(appoint, record_miss=record)
    get_user_logger(appoint).info(f"预约{appoint.pk}已取消")
