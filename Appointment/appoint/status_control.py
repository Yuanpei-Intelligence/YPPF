from datetime import datetime, timedelta

from Appointment.config import appointment_config as CONFIG
from Appointment.models import Appoint
from Appointment.appoint.judge import appoint_violate
from Appointment.utils.log import logger, get_user_logger
from Appointment.extern.wechat import MessageType, notify_appoint


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


def start_appoint(appoint_id: int):
    '''预约开始，切换状态'''
    try:
        appoint = Appoint.objects.get(Aid=appoint_id)
    except:
        return logger.exception(f"预约{appoint_id}意外消失")

    if appoint.Astatus == Appoint.Status.APPOINTED:     # 顺利开始
        appoint.Astatus = Appoint.Status.PROCESSING
        appoint.save()
        logger.info(f"预约{appoint_id}成功开始: 状态变为进行中")

    elif appoint.Astatus == Appoint.Status.PROCESSING:  # 已经开始
        logger.info(f"预约{appoint_id}在检查时已经开始")

    elif appoint.Astatus != Appoint.Status.CANCELED:    # 状态异常，本该不存在这个任务
        logger.error(f"预约{appoint_id}的状态异常: {appoint.get_status()}")


def _teminate_handler(appoint: Appoint):
    if appoint.Astatus == Appoint.Status.CONFIRMED:   # 可能已经判定通过，如公共区域和俄文楼
        rid = appoint.Room.Rid
        if rid[:1] != 'R' and rid not in {'B109A', 'B207'}:
            logger.warning(f"预约{appoint.pk}提前合格: {rid}房间")

    elif appoint.Astatus != Appoint.Status.CANCELED:    # 状态异常，多半是已经判定过了
        logger.warning(f"预约{appoint.pk}提前终止: {appoint.get_status()}")


def finish_appoint(appoint_id: int):
    '''
    结束预约
    - 接受单个预约id
    - 可以处理任何状态的预约
    - 对于非终止状态，判断人数是否合格，并转化为终止状态

    要注意的是，由于定时任务可能执行多次，第二次的时候可能已经终止
    '''
    try:
        appoint: Appoint = Appoint.objects.get(Aid=appoint_id)
    except:
        return logger.exception(f"预约{appoint_id}意外消失")

    # 如果处于非终止状态，只需检查人数判断是否合格
    if appoint.Astatus in Appoint.Status.Terminals():
        return _teminate_handler(appoint)

    # 希望接受的非终止状态只有进行中，但其他状态也同样判定是否合格
    if appoint.Astatus != Appoint.Status.PROCESSING:
        get_user_logger(appoint).error(
            f"预约{appoint_id}结束时状态为{appoint.get_status()}：照常检查是否合格")

    # 摄像头出现超时问题，直接通过
    if datetime.now() - appoint.Room.Rlatest_time > timedelta(minutes=15):
        appoint.Astatus = Appoint.Status.CONFIRMED  # waiting
        appoint.save()
        get_user_logger(appoint).info(f"预约{appoint_id}的状态已确认: 顺利完成")
        return

    # 检查人数是否足够
    adjusted_rate = _adjusted_rate(CONFIG.camera_qualify_rate, appoint)
    need_num = appoint.Acamera_check_num * adjusted_rate - 0.01
    check_failed = appoint.Acamera_ok_num < need_num

    if check_failed:
        # 迟到的预约通知在这里处理。如果迟到不扣分，删掉这个if的内容即可
        # 让下面那个camera check的if判断是否违规。
        if appoint.Areason == Appoint.Reason.R_LATE:
            reason = Appoint.Reason.R_LATE
        else:
            reason = Appoint.Reason.R_TOOLITTLE
        if appoint_violate(appoint, reason):
            appoint.refresh_from_db()
            notify_appoint(appoint, MessageType.VIOLATED, appoint.get_status(),
                            students_id=[appoint.get_major_id()])

    else:   # 通过
        appoint.Astatus = Appoint.Status.CONFIRMED
        appoint.save()
        logger.info(f"预约{appoint_id}人数合格，已通过")
