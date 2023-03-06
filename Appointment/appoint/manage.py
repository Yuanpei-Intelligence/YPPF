from datetime import datetime, timedelta

from django.http import JsonResponse
from django.db import transaction

from Appointment.config import appointment_config as CONFIG
from Appointment.models import Participant, Room, Appoint
from Appointment.utils.identity import get_participant
from Appointment.utils.utils import get_conflict_appoints
from Appointment.utils.log import logger, get_user_logger
from Appointment.jobs import set_scheduler
from Appointment.extern.wechat import MessageType, notify_appoint
from Appointment.extern.jobs import set_appoint_reminder


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
        notify_appoint(appoint, MessageType.NEW_INCOMING, students_id=students_id)
    return True


# 过渡，待废弃
def _success(data):
    return JsonResponse({'data': data}, status=200)


def _error(msg: str, detail=None):
    content = dict(message=msg)
    if detail is not None:
        content.update(detail=str(detail))
    return JsonResponse({'statusInfo': content}, status=400)


def addAppoint(contents: dict,
               type: Appoint.Type = Appoint.Type.NORMAL,
               check_contents: bool = True,
               notify_create: bool = True) -> JsonResponse:
    '''
    创建一个预约，检查各种条件，屎山函数

    :param contents: 屎山，只知道Sid: arg for `get_participant`
    :type contents: dict
    :param type: 预约类型, defaults to Appoint.Type.NORMAL
    :type type: Appoint.Type, optional
    :param check_contents: 是否检查参数，暂未启用, defaults to True
    :type check_contents: bool, optional
    :param notify_create: 是否通知参与者创建了新预约, defaults to True
    :type notify_create: bool, optional
    :return: 屎山
    :rtype: JsonResponse
    '''

    # 首先检查房间是否存在
    try:
        room: Room = Room.objects.get(Rid=contents['Rid'])
        assert room.Rstatus == Room.Status.PERMITTED, 'room service suspended!'
    except Exception as e:
        return _error('房间不可预约，请更换房间！', e)
    # 再检查学号对不对
    students_id = contents['students']  # 存下学号列表
    students = Participant.objects.filter(Sid__in=students_id)  # 获取学生
    try:
        assert students.count() == len(students_id), "students repeat or don't exists"
    except Exception as e:
        return _error('预约人信息有误，请检查后重新发起预约！', e)

    # 检查预约时间是否正确
    try:
        Astart: datetime = contents['Astart']
        Afinish: datetime = contents['Afinish']
        assert isinstance(Astart, datetime), 'Appoint time format error'
        assert isinstance(Afinish, datetime), 'Appoint time format error'
        assert Astart <= Afinish, 'Appoint time error'

        assert Afinish > datetime.now(), 'Appoint time error'
    except Exception as e:
        return _error('非法预约时间段，请不要擅自修改url！', e)

    # 检查预约类型
    if datetime.now().date() == Astart.date() and type == Appoint.Type.NORMAL:
        # 长期预约必须保证预约时达到正常人数要求
        type = Appoint.Type.TODAY

    # 创建预约时要求的人数
    create_min: int = room.Rmin
    if type == Appoint.Type.TODAY:
        create_min = min(create_min, CONFIG.today_min)
    if type == Appoint.Type.TEMPORARY:
        create_min = min(create_min, CONFIG.temporary_min)
    if type == Appoint.Type.INTERVIEW:
        create_min = min(create_min, 1)

    # 实际监控检查要求的人数
    check_need_num = create_min
    if check_need_num > CONFIG.today_min:
        if room.Rid == "B107B":
            # 107b的监控不太靠谱，正下方看不到
            check_need_num -= 2
        elif room.Rid == "B217":
            # 地下室关灯导致判定不清晰，晚上更严重
            check_need_num -= 2 if Astart.hour >= 20 else 1
        # 最多减到当日人数要求
        check_need_num = max(check_need_num, CONFIG.today_min)

    # 检查人员信息
    try:
        yp_num = len(students)
        non_yp_num: int = contents['non_yp_num']
        assert isinstance(non_yp_num, int)
        assert yp_num + \
            non_yp_num >= create_min, f'at least {create_min} students'
    except Exception as e:
        return _error('使用总人数需达到房间最小人数！', e)

    if 2 * yp_num < create_min:
        return _error('院内使用人数需要达到房间最小人数的一半！')

    # 检查如果是俄文楼，是否只有一个人使用
    if room.Rid.startswith('R'):
        if yp_num != 1 or non_yp_num != 0:
            return _error('俄文楼元创空间仅支持单人预约！')

    # 检查如果是面试，是否只有一个人使用
    if type == Appoint.Type.INTERVIEW:
        if yp_num != 1 or non_yp_num != 0:
            return _error('面试仅支持单人预约！')

    # 预约是否超过3小时
    try:
        assert Afinish <= Astart + timedelta(hours=3)
    except:
        return _error('预约时长不能超过3小时！')

    try:
        usage: str = contents['Ausage']
        announcement: str = contents['announcement']
        assert isinstance(usage, str) and isinstance(announcement, str)
    except:
        return _error('非法的预约信息！')

    # 学号对了，人对了，房间是真实存在的，那就开始预约了
    major_student = None    # 避免下面未声明出错
    try:
        with transaction.atomic():
            # 获取预约发起者,确认预约状态
            major_student = get_participant(contents['Sid'])
            if major_student is None:
                return _error('发起人信息不存在！')

            appoint: Appoint = Appoint(
                Room=room,
                Astart=Astart,
                Afinish=Afinish,
                Ausage=usage,
                Aannouncement=announcement,
                major_student=major_student,
                Anon_yp_num=non_yp_num,
                Ayp_num=yp_num,
                Aneed_num=check_need_num,
                Atype=type,
            )
            conflict_appoints = get_conflict_appoints(appoint, lock=True)
            for conflict_appoint in conflict_appoints:
                return _error('预约时间与已有预约冲突，请重选时间段！', conflict_appoint.toJson())

            # 确认信用分符合要求
            if major_student.credit <= 0:
                return _error('信用分不足，本月无法发起预约！')

            # 成功创建
            appoint.save()
            appoint.students.set(students)

            # 设置状态变更和微信提醒定时任务
            set_scheduler(appoint)
            if notify_create:
                _notify_create(appoint, students_id)
            set_appoint_reminder(appoint, students_id)

            get_user_logger(major_student).info(f"发起预约，预约号{appoint.Aid}")

    except Exception as e:
        major_display = major_student.__str__()
        logger.exception(f"学生{major_display}出现添加预约失败的问题: {e}")
        return _error('添加预约失败!请与管理员联系!')

    return _success(appoint.toJson())
