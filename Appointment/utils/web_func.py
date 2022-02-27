import requests as requests
from Appointment import *
from Appointment.models import Participant, Room, Appoint, College_Announcement
from Appointment.utils.identity import get_participant
from django.db.models import Q  # modified by wxy
from datetime import datetime, timedelta, timezone, time, date
import Appointment.utils.utils as utils
from django.http import JsonResponse, HttpResponse  # Json响应


'''
YWolfeee:
web_func.py中保留所有在views.py中使用到了和web发生交互但不直接在urls.py中暴露的函数
这些函数是views.py得以正常运行的工具函数。
函数比较乱，建议实现新函数时先在这里面找找有没有能用的。
'''


def str_to_time(str_time: str):
    """字符串转换成时间"""
    try: return datetime.strptime(str_time,'%Y-%m-%d %H:%M:%S')
    except: pass
    try: return datetime.strptime(str_time,'%Y-%m-%d %H:%M')
    except: pass
    try: return datetime.strptime(str_time,'%Y-%m-%d %H')
    except: pass
    try: return datetime.strptime(str_time,'%Y-%m-%d')
    except: pass
    raise ValueError(str_time)



# added by pht
# 用于调整不同情况下判定标准的不同
def get_adjusted_qualified_rate(original_qualified_rate, appoint) -> float:
    '''
    get_adjusted_qualified_rate(original_qualified_rate : float, appoint) -> float:
        return an adjusted qualified rate according to appoint state
    '''
    min31 = timedelta(minutes=31)
    if appoint.Room.Rid == 'B214':                  # 暂时因无法识别躺姿导致的合格率下降
        original_qualified_rate -= 0.15             # 建议在0.1-0.2之间 前者最严 后者最宽松
    if appoint.Room.Rid == 'B107B':                 # 107B无法监控摄像头下方的问题
        original_qualified_rate -= 0.05             # 建议在0-0.1之间 因为主要是识别出的人数问题
    if appoint.Room.Rid == 'B217' and appoint.Astart.hour >= 20 :   # 电影关灯导致识别不准确
        original_qualified_rate -= 0.05             # 建议在0-0.1之间 因为主要是识别出的人数问题
    if appoint.Afinish - appoint.Astart < min31:    # 减少时间过短时前后未准时到的影响
        original_qualified_rate -= 0.01             # 建议在0-0.1之间 基本取消了
    if appoint.Areason == Appoint.Reason.R_LATE:    # 迟到需要额外保证使用率
        original_qualified_rate += 0.05             # 建议在0.2-0.4之间 极端可考虑0.5 目前仅测试
    if appoint.Atemp_flag:                     # 对于临时预约，不检查摄像头 by lhw（2021.7.13）
        original_qualified_rate = 0
    if appoint.Room.Rid in {'B109A', 'B207'}:       # 公共区域
        original_qualified_rate = 0
    if appoint.Room.Rid[:1] == 'R':                 # 俄文楼
        original_qualified_rate = 0
    return original_qualified_rate


def startAppoint(Aid):  # 开始预约时的定时程序
    try:
        appoint = Appoint.objects.get(Aid=Aid)
    except:
        utils.operation_writer(
            SYSTEM_LOG, f"预约{str(Aid)}意外消失", "web_func.startAppoint", "Error")
        return

    if appoint.Astatus == Appoint.Status.APPOINTED:     # 顺利开始
        appoint.Astatus = Appoint.Status.PROCESSING
        appoint.save()
        utils.operation_writer(
            SYSTEM_LOG, f"预约{str(Aid)}成功开始: 状态变为进行中", "web_func.startAppoint")

    elif appoint.Astatus == Appoint.Status.PROCESSING:  # 已经开始
        utils.operation_writer(
            SYSTEM_LOG, f"预约{str(Aid)}在检查时已经开始", "web_func.startAppoint")

    elif appoint.Astatus != Appoint.Status.CANCELED:    # 状态异常，本该不存在这个任务
        utils.operation_writer(
            SYSTEM_LOG, f"预约{str(Aid)}的状态异常: {appoint.get_status()}", "web_func.startAppoint", "Error")


def finishAppoint(Aid):  # 结束预约时的定时程序
    '''
    结束预约时的定时程序
    - 接受单个预约id
    - 可以处理任何状态的预约
    - 对于非终止状态，判断人数是否合格，并转化为终止状态

    要注意的是，由于定时任务可能执行多次，第二次的时候可能已经终止
    '''
    try:
        appoint = Appoint.objects.get(Aid=Aid)
    except:
        utils.operation_writer(
            SYSTEM_LOG, f"预约{str(Aid)}意外消失", "web_func.finishAppoint", "Error")
        return


    # 避免直接使用全局变量! by pht
    adjusted_camera_qualified_check_rate = GLOBAL_INFO.camera_qualified_check_rate

    # --- add by pht: 终止状态 --- #
    TERMINATE_STATUSES = [
        Appoint.Status.CONFIRMED,
        Appoint.Status.VIOLATED,
        Appoint.Status.CANCELED,
        ]
    # --- add by pht(2021.9.4) --- #

    # 如果处于非终止状态，只需检查人数判断是否合格
    if appoint.Astatus not in TERMINATE_STATUSES:
        # 希望接受的非终止状态只有进行中，但其他状态也同样判定是否合格
        if appoint.Astatus != Appoint.Status.PROCESSING:
            utils.operation_writer(
                # TODO: major_sid
                appoint.major_student.Sid_id,
                f"预约{str(Aid)}结束时状态为{appoint.get_status()}：照常检查是否合格",
                "web_func.finishAppoint", "Error")

        # 摄像头出现超时问题，直接通过
        if datetime.now() - appoint.Room.Rlatest_time > timedelta(minutes=15):
            appoint.Astatus = Appoint.Status.CONFIRMED  # waiting
            appoint.save()
            utils.operation_writer(
                # TODO: major_sid
                appoint.major_student.Sid_id,
                f"预约{str(Aid)}的状态变为{Appoint.Status.CONFIRMED}: 顺利完成",
                "web_func.finishAppoint", "OK")
        else:
            #if appoint.Acamera_check_num == 0:
            #    utils.operation_writer(
            #        SYSTEM_LOG, f"预约{str(Aid)}的摄像头检测次数为零", "web_func.finishAppoint", "Error")
            # 检查人数是否足够

            # added by pht: 需要根据状态调整 出于复用性和简洁性考虑在本函数前添加函数
            # added by pht: 同时出于安全考虑 在本函数中重定义了本地rate 稍有修改 避免出错
            adjusted_camera_qualified_check_rate = get_adjusted_qualified_rate(
                original_qualified_rate=adjusted_camera_qualified_check_rate,
                appoint=appoint
            )

            if appoint.Acamera_ok_num < appoint.Acamera_check_num * adjusted_camera_qualified_check_rate - 0.01:  # 人数不足
                # add by lhw ： 迟到的预约通知在这里处理。如果迟到不扣分，删掉这个if的内容即可，让下面那个camera check的if判断是否违规。
                if appoint.Areason == Appoint.Reason.R_LATE:
                    status, tempmessage = utils.appoint_violate(
                        appoint, Appoint.Reason.R_LATE)
                    if not status:
                        utils.operation_writer(
                            SYSTEM_LOG, f"预约{str(Aid)}因迟到而违约时出现异常: {tempmessage}", "web_func.finishAppoint", "Error")
                else:
                    status, tempmessage = utils.appoint_violate(
                        appoint, Appoint.Reason.R_TOOLITTLE)
                    if not status:
                        utils.operation_writer(
                            SYSTEM_LOG, f"预约{str(Aid)}因人数不够而违约时出现异常: {tempmessage}", "web_func.finishAppoint", "Error")

            else:   # 通过
                appoint.Astatus = Appoint.Status.CONFIRMED
                appoint.save()
                utils.operation_writer(
                    SYSTEM_LOG, f"预约{str(Aid)}人数合格，已通过", "web_func.finishAppoint", "OK")

    else:
        if appoint.Astatus == Appoint.Status.CONFIRMED:   # 可能已经判定通过，如公共区域和俄文楼
            rid = appoint.Room.Rid
            if rid[:1] != 'R' and rid not in {'B109A', 'B207'}:
                utils.operation_writer(
                    SYSTEM_LOG, f"预约{str(Aid)}提前合格: {rid}房间", "web_func.finishAppoint", "Problem")

        elif appoint.Astatus != Appoint.Status.CANCELED:    # 状态异常，多半是已经判定过了
            utils.operation_writer(
                SYSTEM_LOG, f"预约{str(Aid)}提前终止: {appoint.get_status()}", "web_func.finishAppoint", "Problem")
            # appoint.Astatus = Appoint.Status.WAITING
            # appoint.save()


def get_student_chosen_list(request, get_all=False):
    '''用于前端显示支持拼音搜索的人员列表, 形如[{id, text, pinyin}]'''
    js_stu_list = []
    Stu_all = Participant.objects.all()
    if not get_all:
        Stu_all = Stu_all.exclude(hidden=True)
    students = Stu_all.exclude(Sid_id=request.user.username)
    for stu in students:
        Sid = stu.Sid_id
        js_stu_list.append({
            "id": Sid,
            "text": stu.name + "_" + Sid[:2],
            "pinyin": stu.pinyin,
        })
    return js_stu_list


def get_talkroom_timerange(talk_room_list):
    """
    returns :talk toom 的时间range 以及最早和最晚的时间
    int, datetime.time, datetime.time
    """
    t_start = talk_room_list[0].Rstart
    t_finish = talk_room_list[0].Rfinish
    for room in talk_room_list:
        t_start = min(t_start, room.Rstart)
        t_finish = max(t_finish, room.Rfinish)
    return t_start, t_finish


def time2datetime(year, month, day, t):
    return datetime(year, month, day, t.hour, t.minute, t.second)


def appoints2json(appoints):
    if isinstance(appoints, Appoint):
        return appoints.toJson()
    return [appoint.toJson() for appoint in appoints]


def get_appoints(Pid, kind, major=False, to_json=True):
    '''
    - Pid: Participant, User or str
    - kind: `'future'`, `'past'` or `'violate'`
    - returns: {data: objs.toJson() form} or {statusInfo: infos}
    '''
    try:
        participant = Pid
        if not isinstance(Pid, Participant):
            participant = get_participant(participant, raise_except=True)
    except Exception as e:
        return {'statusInfo': {'message': '学号不存在', 'detail': str(e)}}

    present_day = datetime.now()
    seven_days_before = present_day - timedelta(7)

    appoints = participant.appoint_list.all()
    if major:
        appoints = appoints.filter(major_student=participant)

    if kind == 'future':
        appoints = appoints.filter(Astatus=Appoint.Status.APPOINTED,
                                   Astart__gte=present_day)
    elif kind == 'past':
        appoints = appoints.filter((Q(Astart__lte=present_day)
                                    & Q(Astart__gte=seven_days_before))
                                   | (Q(Astart__gte=present_day)
                                      & ~Q(Astatus=Appoint.Status.APPOINTED)))
    elif kind == 'today':
        appoints = appoints.filter(Astart__gte=present_day - timedelta(1),
                                   Astart__lte=present_day + timedelta(1))
    elif kind == 'violate':
        # 只考虑本学期的内容，因此用GLOBAL_INFO过滤掉以前的预约
        start_time = str_to_time(GLOBAL_INFO.semester_start)
        appoints = appoints.filter(Astatus=Appoint.Status.VIOLATED, Astart__gte = start_time)
    else:
        return {'statusInfo': {'message': '参数错误', 'detail': f'kind非法: {kind}'}}

    return {'data': appoints2json(appoints) if to_json else appoints}


# 对一个从Astart到Afinish的预约,考虑date这一天,返回被占用的时段
def timerange2idlist(Rid, Astart, Afinish, max_id):
    room = Room.objects.get(Rid=Rid)
    leftid = max(0, get_time_id(room, Astart.time()))
    rightid = min(get_time_id(room, Afinish.time(), 'leftopen'), max_id) + 1
    return range(leftid, rightid)


def get_hour_time(room, timeid):  # for room , consider its time id
    endtime_id = get_time_id(
        room, room.Rfinish, mode='leftopen')  # 返回最后一个时段的id
    if timeid > endtime_id + 1:  # 说明被恶意篡改，时间过大
        print("要求预约时间大于结束时间,返回23:59")
        return ("23:59"), False
    if (room.Rstart.hour + timeid // 2 == 24):
        return ("23:59"), True
    minute = room.Rstart.hour * 60 + room.Rstart.minute + timeid * 30
    opentime = time(minute // 60, minute % 60, 0)
    return opentime.strftime("%H:%M"), True


def get_time_id(room,
                ttime,
                mode="rightopen"):  # for room. consider a time's timeid
    if ttime < room.Rstart:  # 前置时间,返回-1必定可以
        return -1
    # 超过开始时间
    delta = timedelta(hours=ttime.hour - room.Rstart.hour,
                      minutes=ttime.minute - room.Rstart.minute)  # time gap
    second = int(delta.total_seconds())
    minute, second = divmod(second, 60)
    hour, minute = divmod(minute, 60)
    #print("time_span:", hour, ":", minute,":",second)
    if mode == "rightopen":  # 左闭右开, 注意时间段[6:00,6:30) 是第一段
        half = 0 if minute < 30 else 1
    else:  # 左开右闭,(23:30,24:00]是最后一段
        half = 1 if (minute > 30 or (minute == 30 and second > 0)) else 0
        if minute == 0 and second == 0:  # 其实是上一个时段的末尾
            half = -1
    return hour * 2 + half


def get_dayrange(span=7):   # 获取用户的违约预约
    timerange_list = []
    present_day = datetime.now()
    for i in range(span):
        timerange = {}
        aday = present_day + timedelta(days=i)
        timerange['weekday'] = aday.strftime("%a")
        timerange['date'] = aday.strftime("%d %b")
        timerange['year'] = aday.year
        timerange['month'] = aday.month
        timerange['day'] = aday.day
        timerange_list.append(timerange)
    return timerange_list


# added by wxy
def get_user_info(Pid):
    '''抓取用户信息的通用包，成功返回包含id, name, credit的字典'''
    try:
        participant = Pid
        if not isinstance(Pid, Participant):
            participant = get_participant(participant, raise_except=True)
    except Exception as e:
        return {'statusInfo': {'message': '学号不存在', 'detail': str(e)}}
    return {
        'id': participant.Sid_id,
        'name': participant.name,
        'credit': participant.credit,
    }
