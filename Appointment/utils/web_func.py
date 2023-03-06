from datetime import datetime, timedelta, time
from typing import Dict, Any

from django.db.models import Q, QuerySet

from Appointment.config import appointment_config as CONFIG
from Appointment.models import Participant, Room, Appoint
from Appointment.utils.identity import get_participant

# TODO: 定时任务引入startAppoint和finishAppoint，逐渐删除
from Appointment.appoint.status_control import (
    start_appoint as startAppoint,
    finish_appoint as finishAppoint,
)

'''
YWolfeee:
web_func.py中保留所有在views.py中使用到了和web发生交互但不直接在urls.py中暴露的函数
这些函数是views.py得以正常运行的工具函数。
函数比较乱，建议实现新函数时先在这里面找找有没有能用的。
'''


def get_student_chosen_list(request, queryset, get_all=False):
    '''用于前端显示支持拼音搜索的人员列表, 形如[{id, text, pinyin}]'''
    js_stu_list = []
    Stu_all = queryset
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


def appoints2json(appoints: 'QuerySet[Appoint] | Appoint'):
    if isinstance(appoints, Appoint):
        return appoints.toJson()
    return [appoint.toJson() for appoint in appoints]


def get_appoints(Pid, kind: str, major=False):
    '''
    - Pid: Participant, User or str
    - kind: `'future'`, `'past'` or `'violate'`
    - returns: objs.toJson() form or None if failed
    '''
    try:
        participant = Pid
        if not isinstance(participant, Participant):
            participant = get_participant(participant, raise_except=True)
    except Exception as e:
        return None

    present_day = datetime.now()
    seven_days_before = present_day - timedelta(7)

    appoints: QuerySet[Appoint] = participant.appoint_list.displayable()
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
        # 只考虑本学期的内容，因此用CONFIG过滤掉以前的预约
        appoints = appoints.filter(Astatus=Appoint.Status.VIOLATED,
                                   Astart__gte=CONFIG.semester_start)
    else:
        return None

    return appoints


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


def get_time_id(room: Room, ttime: time, mode: str = "rightopen") -> int:
    """
    返回当前时间的时间块编号，注意编号会与房间的开始预定时间相关。

    :param room: 房间
    :type room: Room
    :param ttime: 当前时间
    :type ttime: time
    :param mode: 左开右闭或左闭右开, defaults to "rightopen"
    :type mode: str
    :return: 当前时间所处的时间块编号
    :rtype: int
    """
    if ttime < room.Rstart:  # 前置时间,返回-1必定可以
        return -1
    # 超过开始时间
    delta = timedelta(hours=ttime.hour - room.Rstart.hour,
                      minutes=ttime.minute - room.Rstart.minute)  # time gap
    second = int(delta.total_seconds())
    minute, second = divmod(second, 60)
    hour, minute = divmod(minute, 60)
    if mode == "rightopen":  # 左闭右开, 注意时间段[6:00,6:30) 是第一段
        half = 0 if minute < 30 else 1
    else:  # 左开右闭,(23:30,24:00]是最后一段
        half = 1 if (minute > 30 or (minute == 30 and second > 0)) else 0
        if minute == 0 and second == 0:  # 其实是上一个时段的末尾
            half = -1
    return hour * 2 + half


def get_dayrange(span: int = 7, day_offset: int = 0):
    """
    生成一个连续的时间段

    :param span: 时间段跨度, defaults to 7
    :type span: int
    :param day_offset: 开始时间与当前时间相差的天数, defaults to 0
    :type day_offset: int
    :return: 时间段列表，每一项包含该天的具体信息、起始日期、结束后下一天
    :rtype: list[dict], date, date
    """
    timerange_list = []
    present_day = datetime.now().date() + timedelta(days=day_offset)
    for i in range(span):
        timerange = {}
        aday = present_day + timedelta(days=i)
        timerange['weekday'] = aday.strftime("%a")
        timerange['date'] = aday.strftime("%d %b")
        timerange['year'] = aday.year
        timerange['month'] = aday.month
        timerange['day'] = aday.day
        timerange_list.append(timerange)
    return timerange_list, present_day, present_day + timedelta(days=span)


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


def appointment2Display(appoint: Appoint, type: str, userid: str = None) -> Dict[str, Any]:
    """
    获取单次预约的信息，填入供前端展示的词典

    :param appoint: 单次预约
    :type appoint: Appoint
    :param type: 展示类型
    :type type: str
    :param userid: 预约人id，长期预约不需要
    :type userid: str
    :return: 供前端展示的词典
    :rtype: dict[str, Any]
    """
    appoint_info = appoint.toJson()
    appoint_info['Astart_hour_minute'] = appoint.Astart.strftime("%I:%M %p")
    appoint_info['Afinish_hour_minute'] = appoint.Afinish.strftime("%I:%M %p")
    if type == 'longterm':
        appoint_info['Aweek'] = appoint.Astart.strftime("%A")
    else:
        appoint_info['is_appointer'] = (userid == appoint.get_major_id())
        appoint_info['can_cancel'] = (type == 'future' and userid == appoint.get_major_id())
    return appoint_info
