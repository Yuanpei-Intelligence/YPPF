import json
from datetime import datetime, timedelta, date
import random

from django.http import JsonResponse
from django.db.models import QuerySet
from django.db import transaction

from utils.global_messages import wrong, succeed, message_url
from Appointment.models import (
    User,
    Participant,
    Room,
    Appoint,
    College_Announcement,
    LongTermAppoint,
)
from Appointment.extern.wechat import MessageType, notify_appoint, notify_user
from Appointment.utils.utils import (
    doortoroom, iptoroom,
    check_temp_appoint, get_conflict_appoints,
    to_feedback_url,
)
from Appointment.utils.log import cardcheckinfo_writer, logger, get_user_logger
import Appointment.utils.web_func as web_func
from Appointment.utils.identity import (
    get_avatar, get_members, get_auditor_ids,
    get_participant, identity_check,
)
from Appointment.appoint.manage import (
    create_require_num,
    create_appoint,
    cancel_appoint,
)
from Appointment.appoint.judge import set_appoint_reason
from Appointment import jobs
from Appointment.config import appointment_config as CONFIG


def _update_check_state(appoint: Appoint, current_num, refresh=False):
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
        # 和上一次检测在同一分钟，此时：1.不增加检测次数 2.如果合规则增加ok次数
        if appoint.Acheck_status == Appoint.CheckStatus.FAILED:
            # 当前不合规；如果这次检测合规，那么认为本分钟合规
            if current_num >= appoint.Aneed_num:
                appoint.Acamera_ok_num += 1
                appoint.Acheck_status = Appoint.CheckStatus.PASSED
        # else:当前已经合规，不需要额外操作


def cameracheck(request):
    '''摄像头post对接的后端函数'''
    # 获取摄像头信号，得到rid,最小人数
    try:
        ip = request.META.get("REMOTE_ADDR")
        current_num = int(json.loads(request.body)['body']['people_num'])
        rid = iptoroom(ip.split(".")[3])  # !!!!!
        room: Room = Room.objects.get(Rid=rid)
    except:
        return JsonResponse({'statusInfo': {'message': '缺少摄像头信息!'}}, status=400)

    # 存储上一次的检测时间
    now_time = datetime.now()
    previous_check_time = room.Rlatest_time

    # 更新现在的人数、最近更新时间
    try:
        with transaction.atomic():
            room.Rpresent = current_num
            room.Rlatest_time = now_time
            room.save()
    except Exception as e:
        logger.exception(f"更新房间{rid}人数失败: {e}")
        return JsonResponse({'statusInfo': {'message': '更新摄像头人数失败!'}}, status=400)

    # 检查时间问题，可能修改预约状态；
    appointments: QuerySet[Appoint] = Appoint.objects.not_canceled().filter(
        Astart__lte=now_time,
        Afinish__gte=now_time,
        Room=room,
    )

    try:
        # 逻辑是尽量宽容，因为一分钟只记录两次，两次随机大概率只有一次成功
        # 所以没必要必须随机成功才能修改错误结果
        refresh = now_time.minute != previous_check_time.minute
        with transaction.atomic():
            for appoint in appointments.select_for_update():
                _update_check_state(appoint, current_num, refresh)
                appoint.save()
                if (now_time > appoint.Astart + timedelta(minutes=15)
                        and appoint.Astatus == Appoint.Status.APPOINTED):
                    # 该函数只是把appoint标记为迟到并修改状态为进行中，不发送微信提醒
                    set_appoint_reason(appoint, Appoint.Reason.R_LATE)
    except Exception as e:
        logger.exception(f"更新预约检查人数失败: {e}")
        return JsonResponse({'statusInfo': {'message': '更新预约状态失败!'}}, status=400)
    return JsonResponse({}, status=200)


def display_getappoint(request):    # 用于为班牌机提供展示预约的信息
    if request.method == "GET":
        try:
            Rid = request.GET.get('Rid')
            display_token = request.GET.get('token', None)
            check = Room.objects.filter(Rid=Rid)
            assert len(check) > 0
            roomname = check[0].Rtitle

            assert display_token is not None
        except:
            return JsonResponse(
                {'statusInfo': {
                    'message': 'invalid params',
                }},
                status=400)
        if display_token != CONFIG.display_token:
            return JsonResponse(
                {'statusInfo': {
                    'message': 'invalid token:'+str(display_token),
                }},
                status=400)

        #appoint = Appoint.objects.get(Aid=3333)
        # return JsonResponse({'data': appoint.toJson()}, status=200,json_dumps_params={'ensure_ascii': False})
        nowtime = datetime.now()
        nowdate = nowtime.date()
        enddate = (nowtime + timedelta(days=3)).date()
        appoints = Appoint.objects.not_canceled().filter(
            Room_id=Rid
        ).order_by("Astart")

        data = [appoint.toJson() for appoint in appoints if
                appoint.Astart.date() >= nowdate and appoint.Astart.date() < enddate
                ]
        comingsoon = appoints.filter(Astart__gt=nowtime,
                                     Astart__lte=nowtime + timedelta(minutes=15))
        comingsoon = 1 if len(comingsoon) else 0    # 有15分钟之内的未开始预约，不允许即时预约

        return JsonResponse(
            {'comingsoon': comingsoon, 'data': data, 'roomname': roomname},
            status=200, json_dumps_params={'ensure_ascii': False})
    else:
        return JsonResponse(
            {'statusInfo': {
                'message': 'method is not get',
            }},
            status=400)


def door_check(request):
    # --------- 对接接口 --------- #
    def _open():
        return JsonResponse({"code": 0, "openDoor": "true"}, status=200)

    def _fail():
        return JsonResponse({"code": 1, "openDoor": "false"}, status=400)
    # --------- 基本信息 --------- #

    # 先以Sid Rid作为参数，看之后怎么改
    Sid, Rid = request.GET.get("Sid", None), request.GET.get("Rid", None)
    student, room, now_time, min15 = None, None, datetime.now(), timedelta(minutes=15)
    # 如果失败会得到None
    student = get_participant(Sid)
    try:
        all_Rid = set(Room.objects.values_list('Rid', flat=True))
        Rid = doortoroom(Rid)
        if Rid[:4] in all_Rid:  # 表示增加了一个未知的A\B号
            Rid = Rid[:4]
        room: Room = Room.objects.get(Rid=Rid)
    except:
        cardcheckinfo_writer(student, room, False, f"房间号{Rid}错误")
        return _fail()
    if student is None:
        cardcheckinfo_writer(student, room, False, f"学号{Sid}错误")
        notify_user(
            Sid, '无法开启该房间',
            '原因：您尚未注册地下室账号，请先访问任意地下室页面创建账号！',
            '点击跳转地下室账户，快捷注册',
            place=room.__str__()
        )
        return _fail()

    # --------- 直接进入 --------- #
    def _check_succeed(message: str):
        cardcheckinfo_writer(student, room, True, message)
        return _open()

    def _check_failed(message: str):
        cardcheckinfo_writer(student, room, False, message)
        return _fail()

    if room.Rstatus == Room.Status.FORBIDDEN:   # 禁止使用的房间
        return _check_failed(f"刷卡拒绝：禁止使用")

    if room.RneedAgree:
        if student.agree_time is None:
            cardcheckinfo_writer(student, room, False, f"刷卡拒绝：未签署协议")
            notify_user(Sid, '您刷卡的房间需要签署协议',
                        '点击本消息即可快捷跳转到用户协议页面',
                        place=room.__str__(), url='agreement', btntxt='签署协议')
            return _fail()

    if room.Rstatus == Room.Status.UNLIMITED:   # 自习室
        if room.RIsAllNight:
            # 通宵自习室
            return _check_succeed(f"刷卡开门：通宵自习室")
        else:
            # 考虑到次晨的情况，判断一天内的时段
            now = timedelta(hours=now_time.hour, minutes=now_time.minute)
            start = timedelta(hours=room.Rstart.hour,
                              minutes=room.Rstart.minute)
            finish = timedelta(hours=room.Rfinish.hour,
                               minutes=room.Rfinish.minute)

            if (now >= min(start, finish) and now <= max(start, finish)) ^ (start > finish):
                # 在开放时间内
                return _check_succeed(f"刷卡开门：自习室")
            return _check_failed(f"刷卡拒绝：自习室不开放")

    # --------- 预约进入 --------- #

    # 获取房间的预约
    room_appoint = Appoint.objects.not_canceled().filter(   # 只选取接下来15分钟进行的预约
        Astart__lte=now_time + min15, Afinish__gte=now_time, Room_id=Rid)

    # --- modify by dyh: 更改规则 --- #
    # --- modify by lhw: 临时预约 --- #

    def _temp_failed(message: str, record_temp=True):
        record_msg = f"刷卡拒绝：临时预约失败（{message}）" if record_temp else f"刷卡拒绝：{message}"
        cardcheckinfo_writer(student, room, False, record_msg)
        notify_user(student.get_id(), '您发起的临时预约失败',
                    '原因：' + message, place=room.__str__())
        return _fail()

    if len(room_appoint) != 0:  # 当前有预约

        # 不是自己的预约
        if not room_appoint.filter(students__in=[student]).exists():
            return _temp_failed(f"该房间有别人的预约，或者距离别人的下一条预约开始不到15min！", False)

        else:   # 自己的预约
            return _check_succeed(f"刷卡开门：预约进入")

    # 当前无预约

    if not check_temp_appoint(room):   # 房间不可以临时预约
        return _temp_failed(f"该房间不可临时预约", False)

    # 该房间可以用于临时预约

    # 注意，由于制度上不允许跨天预约，这里的逻辑也不支持跨日预约（比如从晚上23:00约到明天1:00）。
    # 需要剥离秒级以下的数据，否则admin-index无法正确渲染
    now_time = now_time.replace(second=0, microsecond=0)
    start = now_time
    timeid = web_func.get_time_id(room, start.time())

    finish, valid = web_func.get_hour_time(room, timeid + 1)
    hour, minute = finish.split(':')
    finish = now_time.replace(hour=int(hour), minute=int(minute))

    # 房间未开放
    if timeid < 0 or not valid:
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
    return _check_succeed(f"刷卡开门：临时预约")