import json
import html
from datetime import datetime, timedelta, date
from functools import reduce

from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import auth
from django.db.models import QuerySet
from django.db import transaction

from utils.http import UserRequest, HttpRequest
from utils.global_messages import wrong, succeed, message_url
import utils.global_messages as my_messages
from generic.utils import to_search_indices
from Appointment.models import *
from Appointment.extern.wechat import MessageType, notify_appoint
from Appointment.utils.utils import (
    get_conflict_appoints, to_feedback_url,
)
from Appointment.utils.log import logger, get_user_logger
import Appointment.utils.web_func as web_func
from Appointment.utils.identity import (
    get_avatar, get_member_ids, get_auditor_ids,
    get_participant, identity_check,
)
from Appointment.appoint.manage import (
    create_require_num,
    create_appoint,
    cancel_appoint,
)
from Appointment import jobs
from Appointment.config import appointment_config as CONFIG


# 一些固定值
wklist = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


@require_POST
@identity_check(redirect_field_name='origin')
def cancelAppoint(request: HttpRequest):
    context = {}
    cancel_type = request.POST.get("type")

    if cancel_type == "longterm":
        try:
            pk = int(request.POST.get('cancel_id'))
            longterm_appoint = LongTermAppoint.objects.get(pk=pk)
            assert longterm_appoint.status in [
                LongTermAppoint.Status.REVIEWING,
                LongTermAppoint.Status.APPROVED,
            ]
            assert longterm_appoint.get_applicant_id() == request.user.username
            assert longterm_appoint.sub_appoints().filter(
                Astatus=Appoint.Status.APPOINTED).exists()
        except:
            wrong(f"长期预约不存在或没有权限取消!", context)
            return redirect(message_url(context, reverse("Appointment:account")))
        # 可以取消
        try:
            with transaction.atomic():
                longterm_appoint: LongTermAppoint = (
                    LongTermAppoint.objects.select_for_update().get(pk=pk))
                count = longterm_appoint.cancel()
        except:
            logger.exception(f"取消长期预约{pk}意外失败")
            wrong(f"未能取消长期预约!", context)
            return redirect(message_url(context, reverse("Appointment:account")))

        get_user_logger(longterm_appoint).info(
            f"成功取消长期预约{pk}及{count}条未开始的预约")
        appoint_room_name = str(longterm_appoint.appoint.Room)
        succeed(f"成功取消对{appoint_room_name}的长期预约!", context)
        return redirect(message_url(context, reverse("Appointment:account")))

    try:
        assert cancel_type == 'appoint'
        pk = int(request.POST.get('cancel_id'))
        appoints = Appoint.objects.filter(Astatus=Appoint.Status.APPOINTED)
        appoint: Appoint = appoints.get(pk=pk)
    except:
        return redirect(message_url(
            wrong("预约不存在、已经开始或者已取消!"),
            reverse("Appointment:account")))

    try:
        assert appoint.get_major_id() == request.user.username
    except:
        return redirect(message_url(
            wrong("请不要尝试取消不是自己发起的预约!"),
            reverse("Appointment:account")))

    if (CONFIG.restrict_cancel_time
            and appoint.Astart < datetime.now() + timedelta(minutes=30)):
        return redirect(message_url(
            wrong("不能取消开始时间在30分钟之内的预约!"),
            reverse("Appointment:account")))

    cancel_appoint(appoint, record=True, lock=True)
    succeed(f"成功取消对{appoint.Room.Rtitle}的预约!", context)
    notify_appoint(appoint, MessageType.CANCELED)
    return redirect(message_url(context, reverse("Appointment:account")))


@require_POST
@identity_check(redirect_field_name='origin')
def renewLongtermAppoint(request):
    context = {}
    try:
        pk = int(request.POST.get('longterm_id'))
        longterm_appoint: LongTermAppoint = LongTermAppoint.objects.get(pk=pk)
        assert longterm_appoint.get_applicant_id() == request.user.username
        assert longterm_appoint.status == LongTermAppoint.Status.APPROVED
    except:
        return redirect(message_url(
            wrong("长期预约不存在或不符合续约要求!"),
            reverse("Appointment:account")))

    try:
        times = int(request.POST.get('times'))
        total_times = longterm_appoint.times + times
        assert 1 <= times <= CONFIG.longterm_max_time_once
        assert total_times <= CONFIG.longterm_max_time
        assert total_times * longterm_appoint.interval <= CONFIG.longterm_max_week
    except:
        return redirect(message_url(
            wrong("您选择的续约周数不符合要求!"),
            reverse("Appointment:account")))

    conflict, conflict_appoints = longterm_appoint.renew(times)
    if conflict is None:
        get_user_logger(longterm_appoint).info(f"对长期预约{pk}发起{times}周续约")
        succeed(
            f"成功对{longterm_appoint.appoint.Room}的长期预约进行了{times}周的续约!", context)
    else:
        wrong(f"续约第{conflict}次失败，后续时间段存在预约冲突!", context)
    return redirect(message_url(context, reverse("Appointment:account")))



@identity_check(redirect_field_name='origin')
def account(request: HttpRequest):
    """
    显示用户的预约信息
    """
    render_context = {}
    render_context.update(
        show_admin=(request.user.is_superuser or request.user.is_staff),
    )

    my_messages.transfer_message_context(request.GET,
                                         render_context,
                                         normalize=True)

    # 学生基本信息
    Pid = request.user.username
    my_info = web_func.get_user_info(Pid)
    participant = get_participant(Pid)
    if participant.agree_time is not None:
        my_info['agree_time'] = str(participant.agree_time)

    has_longterm_permission = participant.longterm

    # 头像信息
    img_path = get_avatar(request.user)
    render_context.update(my_info=my_info,
                          img_path=img_path,
                          has_longterm_permission=has_longterm_permission)

    # 获取过去和未来的预约信息
    appoint_list_future = []
    appoint_list_past = []

    for appoint in web_func.get_appoints(Pid, 'future').order_by('Astart'):
        appoint_info = web_func.appointment2Display(appoint, 'future', Pid)
        appoint_list_future.append(appoint_info)

    for appoint in web_func.get_appoints(Pid, 'past').order_by('-Astart'):
        appoint_info = web_func.appointment2Display(appoint, 'past', Pid)
        appoint_list_past.append(appoint_info)

    render_context.update(appoint_list_future=appoint_list_future,
                          appoint_list_past=appoint_list_past)

    if has_longterm_permission:
        # 获取长期预约数据
        appoint_list_longterm = []
        longterm_appoints = LongTermAppoint.objects.filter(
            applicant=participant)
        # 判断是否达到上限
        count = LongTermAppoint.objects.activated().filter(applicant=participant).count()
        is_full = count >= CONFIG.longterm_max_num
        for longterm_appoint in longterm_appoints:
            longterm_appoint: LongTermAppoint
            appoint_info = web_func.appointment2Display(
                longterm_appoint.appoint, 'longterm')

            # 判断是否可以续约
            last_start = longterm_appoint.appoint.Astart + timedelta(
                weeks=(longterm_appoint.times - 1) * longterm_appoint.interval)

            renewable = (longterm_appoint.status == LongTermAppoint.Status.APPROVED
                         and datetime.now() > last_start - timedelta(weeks=2)
                         and datetime.now() < last_start)
            data = {
                'longterm_id': longterm_appoint.pk,
                'appoint': appoint_info,
                'times': longterm_appoint.times,
                'interval': longterm_appoint.interval,
                'status': longterm_appoint.get_status_display(),
                'renewable': renewable,
                'review_comment': longterm_appoint.review_comment,
            }
            appoint_list_longterm.append(data)

        render_context.update(appoint_list_longterm=appoint_list_longterm,
                              longterm_count=count, is_full=is_full)

    # 违约记录申诉
    if request.method == 'POST' and request.POST:
        if request.POST.get('feedback') is not None:
            try:
                url = to_feedback_url(request)
                return redirect(url)
            except AssertionError as e:
                wrong(str(e), render_context)

    return render(request, 'Appointment/admin-index.html', render_context)


@identity_check(redirect_field_name='origin')
def credit(request):

    render_context = {}
    render_context.update(
        show_admin=(request.user.is_superuser or request.user.is_staff),
    )

    my_messages.transfer_message_context(request.GET, render_context)

    # 学生基本信息
    Pid = request.user.username
    my_info = web_func.get_user_info(Pid)
    participant = get_participant(Pid)
    if participant.agree_time is not None:
        my_info['agree_time'] = str(participant.agree_time)

    # 头像信息
    img_path = get_avatar(request.user)
    render_context.update(my_info=my_info, img_path=img_path)

    vio_list = web_func.get_appoints(Pid, 'violate', major=True)

    if request.method == 'POST' and request.POST:
        if request.POST.get('feedback') is not None:
            try:
                url = to_feedback_url(request)
                return redirect(url)
            except AssertionError as e:
                wrong(str(e), render_context)

    vio_list_display = web_func.appoints2json(vio_list)
    for x, appoint in zip(vio_list_display, vio_list):
        x['Astart_hour_minute'] = appoint.Astart.strftime("%I:%M %p")
        x['Afinish_hour_minute'] = appoint.Afinish.strftime("%I:%M %p")
    render_context.update(vio_list=vio_list_display)
    return render(request, 'Appointment/admin-credit.html', render_context)


@identity_check(redirect_field_name='origin', auth_func=lambda x: True)
def index(request):  # 主页
    render_context = {}
    render_context.update(
        show_admin=(request.user.is_superuser or request.user.is_staff),
    )
    # 处理学院公告
    announcements = College_Announcement.objects.filter(
        show=College_Announcement.Show_Status.Yes)
    if announcements:
        render_context.update(announcements=announcements)

    # 获取可能的全局消息
    my_messages.transfer_message_context(request.GET, render_context)

    # --------- 前端变量 ---------#

    room_list = Room.objects.all()
    now, tomorrow = datetime.now(), datetime.today() + timedelta(days=1)
    occupied_rooms = set(Appoint.objects.not_canceled().filter(
        Astart__lte=now + timedelta(minutes=15),
        Afinish__gte=now).values_list('Room__Rid', flat=True))                      # 接下来有预约的房间
    future_appointments = Appoint.objects.not_canceled().filter(
        Astart__gte=now + timedelta(minutes=15), Astart__lt=tomorrow)               # 接下来的预约
    room_appointments = {room.Rid: None for room in room_list}
    for appointment in future_appointments:                                         # 每个房间的预约
        room_appointments[appointment.Room.Rid] = min(
            room_appointments[appointment.Room.Rid] or timedelta(1), appointment.Astart - now)

    def format_time(delta):  # 格式化timedelta，隐去0h
        if delta is None:
            return None
        hour, rem = divmod(delta.seconds, 3600)
        return f"{rem // 60}min" if hour == 0 else f"{hour}h{rem // 60}min"

    # --------- 地下室状态：left tab ---------#
    unlimited_rooms = room_list.unlimited().order_by(
        '-Rtitle')                     # 开放房间
    statistics_info = [(room, (room.Rpresent * 10) // (room.Rmax or 1))
                       for room in unlimited_rooms]                                # 开放房间人数统计
    reservable_room_classes = RoomClass.objects.filter(
        reservable=True).order_by('sort_idx')
    quick_reservable_rooms = reduce(
        lambda x, y: x | y, [set(room_class.rooms.all())
                             for room_class in reservable_room_classes
                             if room_class.quick_reservable], set())
    room_info = [(room, room.Rid in occupied_rooms,
                  format_time(room_appointments[room.Rid]))
                 for room in quick_reservable_rooms]

    render_context.update(
        room_info=room_info,
        statistics_info=statistics_info,
        reservable_room_classes=reservable_room_classes,
    )

    if request.method == "POST":

        request_time = request.POST.get("request_time", None)
        room_class = request.POST.get("room_class", None)
        if not request_time or not room_class:
            return render(request, 'Appointment/index.html', render_context)
        # TODO: Fix this
        day, month, year = int(request_time[:2]), int(
            request_time[3:5]), int(request_time[6:10])
        re_time = datetime(year, month, day)  # 获取目前request时间的datetime结构
        if re_time.date() < datetime.now().date():  # 如果搜过去时间
            render_context.update(
                search_code=1, search_message="请不要搜索已经过去的时间!")
            return render(request, 'Appointment/index.html', render_context)
        elif re_time.date() - datetime.now().date() > timedelta(days=6):
            # 查看了7天之后的
            render_context.update(search_code=1,
                                  search_message="只能查看最近7天的情况!")
            return render(request, 'Appointment/index.html', render_context)
        # 到这里 搜索没问题 进行跳转
        urls = my_messages.append_query(
            reverse("Appointment:arrange_talk"),
            year=year, month=month, day=day, type=room_class)
        return redirect(urls)
    return render(request, 'Appointment/index.html', render_context)


@identity_check(redirect_field_name='origin')
def agreement(request):
    render_context = {}
    participant = get_participant(request.user)
    if request.method == 'POST' and request.POST.get('type', '') == 'confirm':
        try:
            with transaction.atomic():
                participant = get_participant(request.user, update=True)
                participant.agree_time = datetime.now().date()
                participant.save()
            return redirect(message_url(
                succeed('协议签署成功!'),
                reverse("Appointment:account")))
        except:
            my_messages.wrong('签署失败，请重试！', render_context)
    elif request.method == 'POST':
        return redirect(reverse("Appointment:index"))
    if participant.agree_time is not None:
        render_context.update(agree_time=str(participant.agree_time))
    return render(request, 'Appointment/agreement.html', render_context)


@identity_check(redirect_field_name='origin')
def instructions(request):
    render_context = {}
    return render(request, 'Appointment/instructions.html', render_context)


@identity_check(redirect_field_name='origin')
def arrange_time(request: HttpRequest):
    """
    选择预约时间
    """

    room = Room.objects.permitted().get(Rid=request.GET.get('Rid'))
    # 判断当前用户是否可以进行长期预约
    has_longterm_permission = get_participant(request.user).longterm
    is_longterm = (request.GET.get(
        'longterm') == 'on') and has_longterm_permission
    next_week = (request.GET.get('start_week') == '1') and is_longterm
    dayrange_list, start_day, end_next_day = web_func.get_dayrange(
        day_offset=7 if next_week else 0)
    # 获取预约时间的最大时间块id
    max_stamp_id = web_func.get_time_id(room, room.Rfinish, mode="leftopen")

    # 定义时间块状态，与预约状态并不完全一致，时间块状态暂定为以下值，可能需要重新规划

    class TimeStatus:
        AVAILABLE = 0   # 可预约
        PASSED = 1      # 已过期
        NORMAL = 2      # 已被普通预约
        LONGTERM = 3    # 已被长期预约

    for day in dayrange_list:
        timesections = []
        start_hour = room.Rstart.hour
        round_up = int(room.Rstart.minute >= 30)

        for i in range(max_stamp_id + 1):
            timesection = {}
            # 获取时间的可读表达
            timesection['starttime'] = str(
                start_hour + (i + round_up) // 2).zfill(2) + ":" + str(
                    (i + round_up) % 2 * 30).zfill(2)
            timesection['status'] = TimeStatus.AVAILABLE
            timesection['id'] = i
            timesections.append(timesection)
        day['timesection'] = timesections

    # 筛选已经存在的预约
    appoints: QuerySet[Appoint] = Appoint.objects.not_canceled().filter(
        Room_id=room.Rid, Afinish__gte=start_day, Astart__date__lt=end_next_day)

    start_day = dayrange_list[0]
    start_day = date(start_day['year'], start_day['month'], start_day['day'])
    # 给出已有预约的信息
    # TODO: 后续可优化
    for appoint in appoints:
        change_id_list = web_func.timerange2idlist(room.Rid, appoint.Astart,
                                                   appoint.Afinish,
                                                   max_stamp_id)
        appoint_usage = html.escape(appoint.Ausage).replace('\n', '<br/>')
        appointer_name = html.escape(appoint.major_student.name)

        date_id = (appoint.Astart.date() - start_day).days
        day = dayrange_list[date_id]

        display_info = [
            f'{appoint_usage}',
            f'预约者：{appointer_name}',
        ]
        # 根据预约类型标记该时间块的状态和信息
        time_status = TimeStatus.NORMAL
        if has_longterm_permission and appoint.Atype == Appoint.Type.LONGTERM:
            # 查找对应的长期预约
            time_status = TimeStatus.LONGTERM
            max_week = CONFIG.longterm_max_week
            potential_appoints = get_conflict_appoints(
                appoint, times=max_week, week_offset=1 - max_week,
            ).filter(major_student=appoint.major_student)
            potential_longterms = LongTermAppoint.objects.filter(
                appoint__in=potential_appoints)
            related_longterm_appoint = None
            for longterm_appoint in potential_longterms:
                if appoint in longterm_appoint.sub_appoints():
                    related_longterm_appoint = longterm_appoint
                    break

            if related_longterm_appoint is not None:
                display_info.append(
                    jobs.get_longterm_display(
                        times=related_longterm_appoint.times,
                        interval_week=related_longterm_appoint.interval,
                        type="inline",
                    )
                )
        display_info = '<br/>'.join(display_info)

        for i in change_id_list:
            day['timesection'][i]['status'] = time_status
            day['timesection'][i]['display_info'] = display_info

    # 删去今天已经过去的时间
    if not next_week:
        curr_stamp_id = web_func.get_time_id(room, datetime.now().time())
        for i in range(min(max_stamp_id, curr_stamp_id) + 1):
            dayrange_list[0]['timesection'][i]['status'] = TimeStatus.PASSED

    render_context = dict(
        room_object=room,
        is_longterm=is_longterm,
        has_longterm_permission=has_longterm_permission,
        start_week=1 if next_week else 0,
        dayrange_list=dayrange_list,
        # 转换成方便前端使用的形式
        js_dayrange_list=json.dumps(dayrange_list),
        # 获取房间信息，以支持房间切换的功能
        reservable_room_classes=RoomClass.objects.filter(
            reservable=True).order_by('sort_idx'),
        TimeStatus=TimeStatus,
    )
    return render(request, 'Appointment/booking.html', render_context)


@identity_check(redirect_field_name='origin')
def arrange_talk_room(request):

    year = int(request.GET.get("year"))
    month = int(request.GET.get("month"))
    day = int(request.GET.get("day"))
    room_class = str(request.GET.get("type"))
    re_time = datetime(year, month, day)  # 如果有bug 直接跳转
    if (re_time.date() < datetime.now().date()
            or re_time.date() - datetime.now().date() > timedelta(days=6)):
        return redirect(reverse("Appointment:index"))

    room_list = RoomClass.objects.filter(
        reservable=True).get(name=room_class).rooms.all()
    Rids = [room.Rid for room in room_list]
    # TODO: Fix `get_talkroom_timerange`
    t_start, t_finish = web_func.get_talkroom_timerange(
        room_list)  # 对所有讨论室都有一个统一的时间id标准
    t_start = web_func.time2datetime(year, month, day, t_start)  # 转换成datetime类
    t_finish = web_func.time2datetime(year, month, day, t_finish)
    t_range = int(((t_finish - timedelta(minutes=1)) -
                   t_start).total_seconds()) // 1800 + 1  # 加一是因为结束时间不是整点
    rooms_time_list = []  # [[{}] * t_range] * len(Rids)

    width = 100 / len(room_list)

    for sequence, room in enumerate(room_list):
        rooms_time_list.append([])
        for time_id in range(t_range):  # 对每半小时
            rooms_time_list[-1].append({})
            rooms_time_list[sequence][time_id]['status'] = 1  # 初始设置为1（不可预约）
            rooms_time_list[sequence][time_id]['time_id'] = time_id
            rooms_time_list[sequence][time_id]['Rid'] = Rids[sequence]
            temp_hour, temp_minute = t_start.hour, int(t_start.minute >= 30)
            rooms_time_list[sequence][time_id]['starttime'] = str(
                temp_hour + (time_id + temp_minute) // 2).zfill(2) + ":" + str(
                    (time_id + temp_minute) % 2 * 30).zfill(2)

    # 考虑三部分不可预约时间 1：不在房间的预约时间内 2：present_time之前的时间 3：冲突预约
    # 可能冲突的预约
    appoints = Appoint.objects.not_canceled().filter(Room_id__in=Rids,
                                                     Astart__gte=t_start,
                                                     Afinish__lte=t_finish)

    present_time_id = int(
        (datetime.now() - t_start).total_seconds()) // 1800  # 每半小时计 左闭右开

    for sequence, room in enumerate(room_list):
        # case 1
        start_id = int((web_func.time2datetime(year, month, day, room.Rstart) -
                        t_start).total_seconds()) // 1800
        finish_id = int(
            ((web_func.time2datetime(year, month, day, room.Rfinish) -
              timedelta(minutes=1)) - t_start).total_seconds()) // 1800

        for time_id in range(start_id, finish_id + 1):
            rooms_time_list[sequence][time_id]['status'] = 0

        # case 2
        for time_id in range(min(present_time_id + 1, t_range)):
            rooms_time_list[sequence][time_id]['status'] = 1

        # case 3
        for appointment in appoints:
            if appointment.Room.Rid == room.Rid:
                start_id = int(
                    (appointment.Astart - t_start).total_seconds()) // 1800
                finish_id = int(((appointment.Afinish - timedelta(minutes=1)) -
                                 t_start).total_seconds()) // 1800
                appointer_name = html.escape(appointment.major_student.name)
                appoint_usage = html.escape(
                    appointment.Ausage).replace('\n', '<br/>')

                for time_id in range(start_id, finish_id + 1):
                    rooms_time_list[sequence][time_id]['status'] = 1
                    rooms_time_list[sequence][time_id]['display_info'] = '<br/>'.join([
                        f'{appoint_usage}',
                        f'预约者：{appointer_name}',
                    ])

    js_rooms_time_list = json.dumps(rooms_time_list)
    js_weekday = json.dumps(
        {'weekday': wklist[datetime(year, month, day).weekday()]})

    return render(request, 'Appointment/booking-talk.html', locals())


def _notify_longterm_review(longterm: LongTermAppoint, auditor_ids: list[str]):
    '''长期预约的审核老师通知提醒，发送给对应的审核老师'''
    if not auditor_ids:
        return
    infos = []
    if longterm.get_applicant_id() != longterm.appoint.get_major_id():
        infos.append(f'申请者：{longterm.applicant.name}')
    notify_appoint(longterm, MessageType.LONGTERM_REVIEWING, *infos,
                   students_id=auditor_ids, url=f'review?Lid={longterm.pk}')


def _get_content_room(contents: dict) -> Room:
    room_id = contents.get('Rid')
    # TODO: 目前调用时一定存在，后续看情况是处理后调用本函数与否，修改检查方式
    assert isinstance(room_id, str), '房间号格式不合法！'
    room = Room.objects.filter(Rid=room_id).first()
    assert room is not None, f'房间{room_id}不存在！'
    return room

def _get_content_students(contents: dict):
    students_id = contents.get('students')
    # TODO: 目前调用时一定存在，后续看情况是处理后调用本函数与否，修改检查方式
    assert isinstance(students_id, list), '预约人信息有误，请检查后重新发起预约！'
    students = Participant.objects.filter(Sid__in=students_id)
    assert len(students) == len(students_id), '预约人信息有误，请检查后重新发起预约！'
    return students

def _add_appoint(contents: dict, start: datetime, finish: datetime, non_yp_num: int,
               type: Appoint.Type = Appoint.Type.NORMAL,
               notify_create: bool = True) -> tuple[Appoint | None, str]:
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
    :return: (预约, 错误信息)
    :rtype: tuple[Appoint | None, str]
    '''
    from Appointment.appoint.manage import _error

    try:
        room = _get_content_room(contents)
        students = _get_content_students(contents)
    except AssertionError as e:
        return _error(str(e))

    # 检查预约类型
    if datetime.now().date() == start.date() and type == Appoint.Type.NORMAL:
        type = Appoint.Type.TODAY

    # 创建预约时要求的人数
    create_min = create_require_num(room, type)

    # 检查人员信息
    if contents.get('longterm') != 'on' and 2 * len(students) < create_min:
        return _error('院内使用人数需要达到房间最小人数的一半！')

    # 预约是否超过3小时
    # 检查预约时间合法性由create_appoint完成
    try:
        assert finish <= start + timedelta(hours=3)
    except:
        return _error('预约时长不能超过3小时！')

    try:
        usage: str = contents['Ausage']
        announcement: str = contents['announcement']
        assert isinstance(usage, str) and isinstance(announcement, str)
    except:
        return _error('非法的预约信息！')

    # 获取预约发起者,确认预约状态
    major_student = get_participant(contents['Sid'])
    if major_student is None:
        return _error('发起人信息不存在！')

    return create_appoint(
        appointer=major_student,
        students=students,
        room=room, start=start, finish=finish,
        usage=usage, announce=announcement,
        outer_num=non_yp_num,
        type=type,
        notify=notify_create,
    )


@identity_check(redirect_field_name='origin')
def checkout_appoint(request: UserRequest):
    """
    提交预约表单，检查合法性，进行预约
    """
    if request.method == "GET":
        Rid = request.GET.get('Rid')
        weekday = request.GET.get('weekday')
        startid = request.GET.get('startid')
        endid = request.GET.get('endid')
        start_week = request.GET.get('start_week', 0)
        is_longterm = True if request.GET.get('longterm') == 'on' else False
        is_interview = False
    else:
        Rid = request.POST.get('Rid')
        weekday = request.POST.get('weekday')
        startid = request.POST.get('startid')
        endid = request.POST.get('endid')
        is_longterm = True if request.POST.get('longterm') == 'on' else False
        start_week = 0
        is_interview = False
        if is_longterm:
            start_week = request.POST.get('start_week', 0)
            # 长期预约的次数
            times = request.POST.get('times', 0)
            # 间隔为1代表每周，为2代表隔周
            interval = request.POST.get('interval', 0)
        else:
            is_interview = request.POST.get('interview') == 'yes'

    applicant = get_participant(request.user, raise_except=True)
    has_longterm_permission = applicant.longterm
    has_interview_permission = not (applicant.longterm or applicant.hidden)
    has_interview_permission &= Rid in Room.objects.interview_room_ids()

    try:
        # 参数类型转换与合法性检查
        start_week = int(start_week)
        startid = int(startid)
        endid = int(endid)
        if is_longterm and request.method == 'POST':
            assert times, '长期预约周数未填写'
            times = int(times)
            interval = int(interval)
            assert 1 <= interval <= CONFIG.longterm_max_interval, '间隔周数'
        assert weekday in wklist, '星期几'
        assert startid >= 0, '起始时间'
        assert endid >= 0, '结束时间'
        assert endid >= startid, '起始时间晚于结束时间'
        assert start_week == 0 or start_week == 1, '预约周数'
        assert has_longterm_permission or not is_longterm, '没有长期预约权限'
        if is_interview:
            assert has_interview_permission, '没有面试权限'
    except AssertionError as e:
        return redirect(message_url(wrong(f'参数不合法: {e}'), reverse('Appointment:index')))
    except:
        return redirect(message_url(wrong('参数不合法'), reverse('Appointment:index')))

    appoint_params = {
        'Rid': Rid,
        'weekday': weekday,
        'startid': startid,
        'endid': endid,
        'longterm': is_longterm,
        'start_week': start_week,
    }
    room = Room.objects.get(Rid=Rid)
    # 表单参数都统一为可预约的第一周，具体预约哪周根据POST的start_week判断
    dayrange_list = web_func.get_dayrange(day_offset=0)[0]
    for day in dayrange_list:
        if day['weekday'] == appoint_params['weekday']:
            appoint_params['date'] = day['date']
            appoint_params['starttime'], valid = web_func.get_hour_time(
                room, appoint_params['startid'])
            assert valid is True
            appoint_params['endtime'], valid = web_func.get_hour_time(
                room, appoint_params['endid'] + 1)
            assert valid is True
            appoint_params['year'] = day['year']
            appoint_params['month'] = day['month']
            appoint_params['day'] = day['day']
            # 最小人数下限控制
            appoint_params['Rmin'] = room.Rmin
            if start_week == 0 and datetime.now().strftime(
                    "%a") == appoint_params['weekday']:
                appoint_params['Rmin'] = min(CONFIG.today_min,
                                             room.Rmin)
            break
    appoint_params['Sid'] = applicant.get_id()
    appoint_params['Sname'] = applicant.name

    # 准备上下文，此时预约的时间地点、发起人已经固定
    render_context = {}
    render_context.update(room_object=room,
                          appoint_params=appoint_params,
                          has_longterm_permission=has_longterm_permission,
                          has_interview_permission=has_interview_permission,
                          interview_max_count=CONFIG.interview_max_num)

    # 提交预约信息
    if request.method == 'POST':
        contents = dict(request.POST)
        for key in contents.keys():
            if key != "students":
                contents[key] = contents[key][0]
                if key in {'year', 'month', 'day'}:
                    contents[key] = int(contents[key])
        # 处理外院人数
        if contents['non_yp_num'] == "":
            contents['non_yp_num'] = 0
        try:
            non_yp_num = int(contents['non_yp_num'])
            assert non_yp_num >= 0
        except:
            wrong("外院人数有误,请按要求输入!", render_context)
        # 检查是否未填写房间用途
        if not contents['Ausage']:
            wrong("请输入房间用途!", render_context)
        # 处理单人预约
        if "students" not in contents.keys():
            contents['students'] = [contents['Sid']]
        else:
            contents['students'].append(contents['Sid'])
        
        # 不允许用非活跃用户凑数
        # 虽然在生成搜索列表时已经排除了非活跃用户，但这里再检查一次，以防万一
        contents['students'] = list(filter(
            lambda sid: User.objects.get(username = sid).active,
            contents['students']
        ))

        # 检查预约次数
        if is_longterm and not (1 <= times <= CONFIG.longterm_max_time_once
                                and 1 <= interval * times <= CONFIG.longterm_max_week):
            wrong("您填写的预约周数不符合要求", render_context)

        # 检查长期预约次数
        if is_longterm and LongTermAppoint.objects.activated().filter(
                applicant=applicant).count() >= CONFIG.longterm_max_num:
            wrong("您的长期预约总数已超过上限", render_context)

        # 检查面试次数
        if is_interview and Appoint.objects.unfinished().filter(
                major_student=applicant, Atype=Appoint.Type.INTERVIEW
        ).count() >= CONFIG.interview_max_num:
            wrong('您预约的面试次数已达到上限，结束后方可继续预约', render_context)

        # 检查预约人活跃情况
        if not applicant.Sid.active:
            wrong('您已毕业，不能预约地下室', render_context)

        start_time = datetime(contents['year'], contents['month'], contents['day'],
                              *map(int, contents['starttime'].split(":")))
        end_time = datetime(contents['year'], contents['month'], contents['day'],
                            *map(int, contents['endtime'].split(":")))
        # TODO: 隔周预约的处理可优化，根据start_week调整实际预约时间
        start_time += timedelta(weeks=start_week)
        end_time += timedelta(weeks=start_week)
        if my_messages.get_warning(render_context)[0] is None:
            # 参数检查全部通过，下面开始创建预约
            appoint_type = Appoint.Type.NORMAL
            _notify = True
            if is_longterm:
                appoint_type = Appoint.Type.LONGTERM
                _notify = False
            elif is_interview:
                appoint_type = Appoint.Type.INTERVIEW
            response = _add_appoint(contents, start_time, end_time, non_yp_num=non_yp_num,
                                    type=appoint_type, notify_create=_notify)
            appoint, err_msg = response
            if appoint is not None and not is_longterm:
                # 成功预约且非长期
                return redirect(
                    message_url(succeed(f"预约{room.Rtitle}成功!"),
                                reverse("Appointment:account")))
            elif appoint is None:
                wrong(err_msg, render_context)
            else:
                # 长期预约
                try:
                    conflict_appoints = []
                    with transaction.atomic():
                        appoint.refresh_from_db()
                        conflict_appoints = get_conflict_appoints(
                            appoint, times - 1, interval,
                            week_offset=interval, exclude_this=True, lock=True)
                        assert not conflict_appoints
                        longterm: LongTermAppoint = LongTermAppoint.objects.create(
                            appoint=appoint,
                            applicant=applicant,
                            times=times,
                            interval=interval,
                        )
                        # 生成后续预约
                        conflict, conflict_appoints = longterm.create()
                        assert conflict is None, f"创建长期预约意外失败"
                        # 向审核老师发送微信通知
                        auditor_ids = get_auditor_ids(longterm.applicant)
                        _notify_longterm_review(longterm, auditor_ids)
                        return redirect(
                            message_url(succeed(f"申请长期预约成功，请等待审核。"),
                                        reverse("Appointment:account")))
                except:
                    appoint.delete()
                    if conflict_appoints:
                        wrong(f"与预约时间为{conflict_appoints[0].Astart}"
                              + f"-{conflict_appoints[0].Afinish}的预约发生冲突",
                              render_context)

    # 提供搜索功能的数据
    search_users = User.objects.filter_type(User.Type.PERSON)
    search_users = search_users.exclude(pk=request.user.pk)
    # 保证都在预约人员列表中且不是隐藏用户
    search_users = search_users.filter(
        pk__in=Participant.objects.filter(hidden=False).values('Sid__pk'))
    stu_list = to_search_indices(search_users, active=True)
    member_ids = get_member_ids(request.user)

    # 用于前端的JSON数据，由Django标签在渲染时转化为JSON格式
    json_context = dict(user_infos=stu_list, member_ids=member_ids)
    render_context.update(json_context=json_context)

    if request.method == 'POST':
        # 预约失败。补充一些已有信息，以避免重复填写
        selected_ids = set(contents.pop('students'))
        selected_ids = [w['id'] for w in stu_list if w['id'] in selected_ids]
        json_context.update(selected_ids=selected_ids)
        render_context.update(contents=contents, show_clause=True)
    return render(request, 'Appointment/checkout.html', render_context)


def review(request: HttpRequest):
    """
    长期预约的审核页面，当前暂不考虑聚合页面
    """
    render_context = {}
    Lid = request.GET.get("Lid")
    if Lid is None:
        return redirect(message_url(
            wrong("当前没有需要审核的长期预约!"),
            reverse("Appointment:account")))

    # 权限检查
    try:
        longterm_appoint: LongTermAppoint = LongTermAppoint.objects.get(pk=Lid)
        reviewer_list = get_auditor_ids(longterm_appoint.applicant)
        if request.user.is_staff and User.objects.check_perm(request.user, LongTermAppoint, 'view'):
            reviewer_list.append(request.user.username)
        assert request.user.username in reviewer_list
    except:
        return redirect(message_url(
            wrong("抱歉，您没有权限审核当前的长期预约!"),
            reverse("Appointment:account")))

    if request.method == "POST":
        try:
            operation = request.POST["operation"]
            assert operation in ["approve", "reject"]
        except:
            return redirect(message_url(
                wrong("非法的操作类型!"),
                reverse("Appointment:account")))
        # 处理预约状态
        if operation == "approve":
            try:
                with transaction.atomic():
                    longterm_appoint.status = LongTermAppoint.Status.APPROVED
                    longterm_appoint.save()
                    notify_appoint(longterm_appoint, MessageType.LONGTERM_APPROVED,
                                   students_id=[longterm_appoint.get_applicant_id()])
                succeed(
                    f"已通过对{longterm_appoint.appoint.Room}的长期预约!", render_context)
            except:
                wrong(f"对于该条长期预约的通过操作失败！", render_context)

        elif operation == "reject":
            try:
                with transaction.atomic():
                    reason = request.POST.get("reason", "")
                    longterm_appoint.cancel()
                    longterm_appoint.status = LongTermAppoint.Status.REJECTED
                    longterm_appoint.review_comment = reason
                    longterm_appoint.save()
                    notify_appoint(
                        longterm_appoint, MessageType.LONGTERM_REJECTED, reason,
                        students_id=[longterm_appoint.get_applicant_id()])
            except:
                wrong(f"对于该条长期预约的拒绝操作失败!", render_context)

    # display的部分
    last_date = longterm_appoint.appoint.Astart + timedelta(
        weeks=longterm_appoint.interval*(longterm_appoint.times - 1))
    render_context.update(
        longterm_appoint=longterm_appoint, last_date=last_date)

    return render(request, "Appointment/review-single.html", render_context)


def logout(request):    # 登出系统
    auth.logout(request)
    return redirect(reverse('Appointment:index'))
