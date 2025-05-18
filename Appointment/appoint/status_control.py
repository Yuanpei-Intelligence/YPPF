from datetime import datetime, timedelta

from django.db import transaction

from Appointment.config import appointment_config as CONFIG
from Appointment.models import Appoint
from Appointment.appoint.judge import appoint_violate
from Appointment.utils.log import logger, get_user_logger
from Appointment.extern.wechat import MessageType, notify_appoint
from Appointment.haikang_api import HaikangSDK, HaikangAPIError


def _adjusted_rate(original_rate: float, appoint: Appoint) -> float:
    '''获取用于调整不同情况下的合格率要求'''
    rate = original_rate
    if appoint.Room.Rid in {'B109A', 'B207'}:   # 公共区域
        return 0
    elif appoint.Room.Rid.startswith('R'):      # 俄文楼
        return 0
    elif appoint.Room.Rid == 'B214':            # 暂时无法识别躺姿
        rate -= 0.15                # 建议在0.1-0.2之间 前者最严 后者最宽松
    elif appoint.Room.Rid == 'B107B':           # 无法监控摄像头正下方
        rate -= 0.05                # 建议在0-0.1之间 因为主要是识别出的人数问题
    elif appoint.Room.Rid == 'B217':
        if appoint.Astart.hour >= 20 :          # 电影关灯导致识别不准确
            rate -= 0.05            # 建议在0-0.1之间 因为主要是识别出的人数问题

    MIN31 = timedelta(minutes=31)
    if appoint.Atype == Appoint.Type.TEMPORARY: # 临时预约不检查摄像头
        return 0
    if appoint.Atype == Appoint.Type.LONGTERM:  # 长期预约不检查摄像头
        return 0
    if appoint.Afinish - appoint.Astart < MIN31:    # 短预约早退晚到影响更大
        rate -= 0.01             # 建议在0-0.1之间 基本取消了
    if appoint.Areason == Appoint.Reason.R_LATE:    # 迟到需要额外保证使用率
        rate += 0.05             # 建议在0.2-0.4之间 极端可考虑0.5 目前仅测试
    return rate

    
@transaction.atomic
def start_appoint_ahead(appoint_id: int):
    try:
        appoint = Appoint.objects.select_for_update().get(Aid=appoint_id)
    except:
        return logger.exception(f"预约{appoint_id}意外消失")
    current = datetime.now()
    if not Appoint.objects.filter(Astart__lt=current, Afinish__gt=current, Room=appoint.Room).exists():
        start_appoint(appoint_id)


@transaction.atomic
def start_appoint(appoint_id: int):
    '''预约开始，切换状态'''
    try:
        appoint = Appoint.objects.select_for_update().get(Aid=appoint_id)
    except:
        return logger.exception(f"预约{appoint_id}意外消失")

    if appoint.Astatus == Appoint.Status.APPOINTED:     # 顺利开始
        if appoint.Afinish > datetime.now():
            # 还未结束，可以开始
            stu_ids = appoint.students_manager.values_list('cross_sys_uid', flat=True)
            for entrance_guard in appoint.Room.entrance_guards.all():
                with HaikangSDK.get_entrace_guard_device(entrance_guard) as device:
                    try:
                        device.grant_access(stu_ids)
                    except HaikangAPIError as e:
                        logger.error(f'预约{appoint.pk}对门禁{entrance_guard.door_id}授权失败：{e}')
                        # 授权失败，让预约保持在 APPOINTED 状态
                        return
            appoint.Astatus = Appoint.Status.PROCESSING
            logger.info(f"预约{appoint_id}成功开始: 状态变为进行中")
        else:
            appoint.Astatus = Appoint.Status.CONFIRMED
            logger.error(f"预约{appoint_id}开始时已经结束")
        appoint.save()

    elif appoint.Astatus == Appoint.Status.PROCESSING:  # 已经开始
        logger.info(f"预约{appoint_id}在检查时已经开始")

    elif appoint.Astatus != Appoint.Status.CANCELED:    # 状态异常，本该不存在这个任务
        logger.error(f"预约{appoint_id}的状态异常: {appoint.get_status()}")


@transaction.atomic
def finish_appoint(appoint_id: int):
    '''
    结束预约
    - 接受单个预约id
    - 可以处理任何状态的预约
    - 对于非终止状态，判断人数是否合格，并转化为终止状态

    '''
    try:
        appoint: Appoint = Appoint.objects.select_for_update().get(Aid=appoint_id)
    except:
        return logger.exception(f"预约{appoint_id}意外消失")

    if appoint.Astatus != Appoint.Status.PROCESSING:
        logger.error(f"预约{appoint_id}结束时状态为{appoint.get_status()}")
        return

    # 更新设备权限
    stu_ids = set(appoint.students_manager.values_list('cross_sys_uid', flat=True))
    # 若该房间还有晚结束且进行中的预约，不能撤销重复人员的权限
    # TODO: Likely to race lock for next appoint's start
    # Do we need to do something?
    next_appoint = Appoint.objects.filter(
        Room=appoint.Room, Afinish__gt=appoint.Afinish,
        Astatus=Appoint.Status.PROCESSING).select_for_update().first()
    if next_appoint:
        next_stu_ids = set(next_appoint.students_manager.values_list('cross_sys_uid', flat=True))
        stu_ids = stu_ids - next_stu_ids
    for entrance_guard in appoint.Room.entrance_guards.all():
        with HaikangSDK.get_entrace_guard_device(entrance_guard) as device:
            try:
                device.revoke_access(stu_ids)
            except HaikangAPIError as e:
                logger.error(f'预约{appoint.pk}对门禁{entrance_guard.door_id}授权失败：{e}')
                # 撤销权限失败，让预约保持在 PROCESSING 状态
                return

    # TODO: 人数检查
    appoint.Astatus = Appoint.Status.CONFIRMED
    appoint.save()
