import json
import random
from datetime import datetime, timedelta

from django.http import JsonResponse, HttpRequest
from django.db.models import QuerySet
from django.db import transaction

from Appointment.models import Room, Appoint, Participant, CardCheckInfo
from Appointment.extern.wechat import notify_user
from Appointment.utils.utils import door2room, ip2room
from Appointment.utils.log import logger
import Appointment.utils.web_func as web_func
from Appointment.utils.identity import get_participant
from Appointment.appoint.manage import create_appoint
from Appointment.appoint.judge import set_appoint_reason
from Appointment.config import appointment_config as CONFIG


def _update_camera_check_state(appoint: Appoint, current_num: int, refresh=False):
    if appoint.Acheck_status == Appoint.CheckStatus.UNSAVED or refresh:
        # 说明是新的一分钟或者本分钟还没有记录
        # 如果随机成功，记录新的检查结果
        if random.uniform(0, 1) < CONFIG.check_rate:
            appoint.Acheck_status = Appoint.CheckStatus.FAILED
            appoint.Acamera_check_num += 1
            if current_num >= appoint.Aneed_num:  # 如果本次检测合规
                appoint.Acamera_ok_num += 1
                appoint.Acheck_status = Appoint.CheckStatus.PASSED
        # 如果随机失败，锁定上一分钟的结果
        else:
            if appoint.Acheck_status == Appoint.CheckStatus.FAILED:
                # 如果本次检测合规，宽容时也算上一次通过（因为一分钟只检测两次）
                if current_num >= appoint.Aneed_num:
                    appoint.Acamera_ok_num += 1
            # 本分钟暂无记录
            appoint.Acheck_status = Appoint.CheckStatus.UNSAVED
    else:
        # Appoint.CheckStatus可能是：PASSED，FAILED
        # 和上一次检测在同一分钟，此时：1.不增加检测次数 2.如果合规则增加ok次数
        if appoint.Acheck_status == Appoint.CheckStatus.FAILED:
            # 当前（上一次检查）不合规；如果这次检测合规，那么认为本分钟合规
            if current_num >= appoint.Aneed_num:
                appoint.Acamera_ok_num += 1
                appoint.Acheck_status = Appoint.CheckStatus.PASSED
        # else:当前已经合规，不需要额外操作，本分钟视为合规
    appoint.save()


def _record_cardcheck(user: Participant | None, room: Room, real_status, message=None):
    CardCheckInfo.objects.create(
        Cardroom=room, Cardstudent=user,
        CardStatus=real_status, Message=message
    )


def _doorid2room(DoorId: str) -> Room | None:
    """什么破东西，懒得改了"""
    try:
        all_Rid = set(Room.objects.values_list('Rid', flat=True))
        Rid = door2room(DoorId)
        if Rid[:4] in all_Rid:  # 表示增加了一个未知的A\B号
            Rid = Rid[:4]
        room: Room = Room.objects.get(Rid=Rid)
        return room
    except:
        return None


def _in_opening_time(room: Room):
    """也很奇怪"""
    # 考虑到次晨的情况，判断一天内的时段
    now = timedelta(hours=datetime.now().hour, minutes=datetime.now().minute)
    start = timedelta(hours=room.Rstart.hour, minutes=room.Rstart.minute)
    finish = timedelta(hours=room.Rfinish.hour, minutes=room.Rfinish.minute)
    # 前者是now在两者中间，后者是跨天开放，两个条件通过异或连接，无论开放、结束时间是否在同一天都能够处理
    if (min(start, finish) <= now <= max(start, finish)) ^ (start > finish):
        # 在开放时间内
        return True
    else:
        return False


def _temp_appoint_valid(room: Room):
    # 注意，由于制度上不允许跨天预约，这里的逻辑也不支持跨日预约（比如从晚上23:00约到明天1:00）。
    # 需要剥离秒级以下的数据，否则admin-index无法正确渲染
    now_time = datetime.now().replace(second=0, microsecond=0)
    start = now_time
    timeid = web_func.get_time_id(room, start.time())

    finish, valid = web_func.get_hour_time(room, timeid + 1)
    hour, minute = finish.split(':')
    finish = now_time.replace(hour=int(hour), minute=int(minute))

    return start, finish, timeid, valid


def cameracheck(request: HttpRequest):
    '''摄像头post对接的后端函数'''
    # 获取摄像头信号，得到rid,最小人数
    try:
        ip = request.META.get("REMOTE_ADDR")
        rid = ip2room(ip.split(".")[3])  # !!!!!
    except:
        return JsonResponse({'statusInfo': {'message': 'invalid or null remote address'}}, status=400)
    room: Room = Room.objects.get(Rid=rid)

    try:
        current_num = int(json.loads(request.body)['body']['people_num'])
    except:
        return JsonResponse({'statusInfo': {'message': '缺少摄像头人数信息!'}}, status=400)

    # 存储上一次的检测时间
    now_time = datetime.now()
    previous_check_time = room.Rlatest_time

    # 更新现在的人数、最近更新时间
    try:
        # 保证：若有一个数据更新失败，则所有数据都不会被更新
        Room.objects.filter(Rid=rid).update(
            Rpresent=current_num, Rlatest_time=now_time)
    except Exception as e:
        logger.exception(f"更新房间{rid}人数失败: {e}")
        return JsonResponse({'statusInfo': {'message': '更新摄像头人数失败!'}}, status=400)

    # 检查时间问题，可能修改预约状态；
    appointments: QuerySet[Appoint] = Appoint.objects.not_canceled().filter(
        Astart__lte=now_time,
        Afinish__gte=now_time,
        Room=room,
    )

    # 逻辑是尽量宽容，因为一分钟只记录两次，两次随机大概率只有一次成功
    # 所以没必要必须随机成功才能修改错误结果
    refresh = (now_time.minute != previous_check_time.minute)
    with transaction.atomic():
        for appoint in appointments.select_for_update():
            try:
                _update_camera_check_state(appoint, current_num, refresh)
                if (now_time > appoint.Astart + timedelta(minutes=15)
                        and appoint.Astatus == Appoint.Status.APPOINTED):
                    # 该函数只是把appoint标记为迟到并修改状态为进行中，不发送微信提醒
                    set_appoint_reason(appoint, Appoint.Reason.R_LATE)
            except Exception as e:
                logger.exception(f"更新预约 {appoint.Aid} 检查人数失败: {e}")
                return JsonResponse({'statusInfo': {'message': f'更新预约 {appoint.Aid} 状态失败!'}}, status=400)

    return JsonResponse({'statusInfo': {'message': '更新成功！'}}, status=200)


def display_getappoint(request: HttpRequest):    # 用于为班牌机提供展示预约的信息
    # ----- Check input
    if request.method != 'GET':
        return JsonResponse({'statusInfo': {'message': 'Method not allowed'}}, status=400)
    Rid = request.GET.get('Rid')
    room = Room.objects.filter(Rid=Rid).first()
    display_token = request.GET.get('token')
    if room is None:
        return JsonResponse(
            {'statusInfo': {
                'message': f'Room with {Rid} not found.',
            }},
            status=400)
    if display_token != CONFIG.display_token:
        return JsonResponse(
            {'statusInfo': {
                'message': 'Invalid token: '+str(display_token),
            }},
            status=400)

    # ----- Do the real work
    now = datetime.now()
    today = now.date()
    end_date = today + timedelta(days=3)
    # TODO: Does Astart__date__gte work?
    appoints = Appoint.objects.not_canceled().filter(Room_id=Rid).order_by("Astart")
    data = [appoint.toJson() for appoint in appoints
            if appoint.Astart.date() >= today and appoint.Astart.date() < end_date
            ]
    comingsoon = appoints.filter(
        Astart__gt=now,
        Astart__lte=now + timedelta(minutes=15)).exists()
    return JsonResponse(
        {'comingsoon': comingsoon, 'data': data, 'roomname': room.Rtitle},
        status=200, json_dumps_params={'ensure_ascii': False})


def door_check(request: HttpRequest):
    """还得接着拆"""

    # --------- 对接接口 --------- #
    def _open(message: str):
        _record_cardcheck(student, room, True, message)
        return JsonResponse({"code": 0, "openDoor": "true"}, status=200)

    def _fail(message: str):
        _record_cardcheck(student, room, False, message)
        return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

    # --------- 基本信息 --------- #
    Sid, DoorId = request.GET.get("Sid", None), request.GET.get("Rid", None)
    student = get_participant(Sid)
    room = _doorid2room(DoorId)
    if room is None:
        return _fail(f"房间门牌号{DoorId}错误")
    if student is None:
        notify_user(
            Sid, '无法开启该房间',
            '原因：您尚未注册地下室账号，请先访问任意地下室页面创建账号！',
            '点击跳转地下室账户，快捷注册',
            place=room.__str__()
        )
        return _fail(f"学号{Sid}错误")

    # --------- 直接进入 --------- #

    # 检查该房间的状态
    if room.Rstatus == Room.Status.FORBIDDEN:   # 禁止使用的房间
        return _fail(f"刷卡拒绝：禁止使用")

    if room.RneedAgree and student.agree_time is None:
        notify_user(Sid, '您刷卡的房间需要签署协议',
                    '点击本消息即可快捷跳转到用户协议页面',
                    place=room.__str__(), url='agreement', btntxt='签署协议')
        return _fail(f"刷卡拒绝：未签署协议")

    if room.Rstatus == Room.Status.UNLIMITED:   # 自习室
        if room.RIsAllNight:
            # 通宵自习室
            return _open(f"刷卡开门：通宵自习室")
        else:
            if _in_opening_time(room):
                return _open(f"刷卡开门：自习室")
            else:
                return _fail(f"刷卡拒绝：自习室不开放")

    # --------- 预约进入 --------- #

    # 用于临时预约失败的通知
    def _temp_failed(message: str, record_temp=True):
        record_msg = f"刷卡拒绝：临时预约失败（{message}）" if record_temp else f"刷卡拒绝：{message}"
        notify_user(Sid, '您发起的临时预约失败',
                    '原因：' + message, place=room.__str__())
        return _fail(record_msg)

    # 获取房间的预约
    room_appoint = Appoint.objects.not_canceled().filter(   # 只选取接下来15分钟进行的预约
        Astart__lte=datetime.now() + timedelta(minutes=15), Afinish__gte=datetime.now(), Room=room)

    # --- modify by dyh: 更改规则 --- #
    # --- modify by lhw: 临时预约 --- #

    # 当前有预约
    if len(room_appoint) != 0:

        # 不是自己的预约
        if not room_appoint.filter(students__in=[student]).exists():
            return _temp_failed(f"该房间有别人的预约，或者距离别人的下一条预约开始不到15min！")

        else:   # 自己的预约
            return _open(f"刷卡开门：预约进入")

    # 当前无预约

    # 房间不可以临时预约
    if not room.quick_reservable:
        return _temp_failed(f"该房间不可临时预约", False)

    # 该房间可以用于临时预约
    start, finish, timeid, valid = _temp_appoint_valid(room)

    # 房间未开放
    if timeid < 0:
        return _temp_failed(f"该时段房间未开放！别熬夜了，回去睡觉！")

    # 检查时间是否合法
    # 合法条件：为避免冲突，临时预约时长必须超过15分钟；预约时在房间可用时段
    # OBSELETE: 时间合法（暂时将间隔定为5min）
    if not valid:
        return _temp_failed(f"预约时间不合法，请不要恶意篡改数据！")

    appoint, err_msg = create_appoint(student, room, start, finish, '临时预约',
                                      type=Appoint.Type.TEMPORARY)

    if appoint is None:
        return _temp_failed(err_msg)
    return _open(f"刷卡开门：临时预约")
