# 数据库模型与操作
import os
import pypinyin  # 支持拼音搜索系统
from Appointment.models import Participant, Room, Appoint, College_Announcement
from django.db.models import Q  # modified by wxy
from django.db import transaction  # 原子化更改数据库

# Http操作相关
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from django.contrib import auth
import json  # 读取Json请求
import html  # 解码保证安全

# csrf 检测和完善
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token

# 时间任务
from datetime import datetime, timedelta, timezone, time, date
import random
import threading

# 全局参数读取
from Appointment import *

# 消息读取
from boottest.global_messages import wrong, succeed, message_url
import boottest.global_messages as my_messages

# utils对接工具
from Appointment.utils.utils import send_wechat_message, appoint_violate, doortoroom, iptoroom, operation_writer, write_before_delete, cardcheckinfo_writer, check_temp_appoint, set_appoint_reason
import Appointment.utils.web_func as web_func
from Appointment.utils.identity import (
    get_name, get_avatar, get_member_ids, get_members,
    get_participant, identity_check,
)

# 定时任务注册
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job
import Appointment.utils.scheduler_func as scheduler_func

'''

Views.py 使用说明
    尽可能把所有工具类的函数放到utils文件夹对应的py下，保持views.py中基本上是直接会被web调用的函数(见urls.py)
    如果存在一些依赖较多的函数，可以留在views.py中

'''

# 日志操作相关
# 返回数据的接口规范如下：(相当于不返回，调用函数写入日志)
# operation_writer(
#   user,
#   message,
#   source,
#   status_code
# )
# user表示这条数据对应的log记录对象，为Sid或者是system_log
# message记录这条log的主体信息
# source表示写入这个log的位置，表示为"文件名.函数名"
# status_code为"OK","Problem","Error",其中Error表示需要紧急处理的问题，会发送到管理员的手机上

# 一些固定值
wklist = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


@csrf_exempt
def getAppoint(request):    # 班牌机对接程序
    raise NotImplementedError
    if request.method == 'POST':  # 获取所有预约信息
        appoints = Appoint.objects.not_canceled()
        data = [appoint.toJson() for appoint in appoints]
        return JsonResponse({'data': data})
    elif request.method == 'GET':  # 获取某条预约信息
        try:
            Rid = request.GET.get('Rid', None)
            assert Rid is not None
            appoints = Appoint.objects.filter(Room_id=str(Rid))
        except Exception as e:
            return JsonResponse(
                {'statusInfo': {
                    'message': 'Room does not exist, please recheck Rid',
                    'detail': str(e)
                }},
                status=400)
        t1 = datetime.now()
        td = timedelta(days=1)
        t2 = t1 + td
        data = [appoint.toJson() for appoint in appoints if appoint.Astart >
                t1 and appoint.Astart < t2 and appoint.Astatus != Appoint.Status.CANCELED]
        try:
            assert len(data) > 0
        except:
            return JsonResponse(
                {
                    'data': data,
                    "empty": 1
                },
                status=200
            )
        return JsonResponse(
            {
                'data': data,
                "empty": 0
            }, status=200)


camera_lock = threading.RLock()


@csrf_exempt
def cameracheck(request):   # 摄像头post的后端函数

    # 获取摄像头信号，得到rid,最小人数
    try:
        ip = request.META.get("REMOTE_ADDR")
        temp_stu_num = int(
            # eval(request.body.decode('unicode-escape'))['body']['people_num'])
            json.loads(request.body)['body']['people_num'])
        rid = iptoroom(ip.split(".")[3])  # !!!!!
        # rid = 'B221'  # just for debug
        room = Room.objects.get(Rid=rid)  # 获取摄像头信号
        num_need = room.Rmin  # 最小房间人数
    except:
        return JsonResponse({'statusInfo': {
            'message': '缺少摄像头信息!',
        }},
            status=400)
    now_time = datetime.now()

    # 存储上一次的检测时间
    room_previous_check_time = room.Rlatest_time

    # 更新现在的人数、最近更新时间
    try:
        with transaction.atomic():
            room.Rpresent = temp_stu_num
            room.Rlatest_time = now_time
            room.save()

    except Exception as e:
        operation_writer(SYSTEM_LOG, "房间"+str(rid) +
                         "更新摄像头人数失败1: "+str(e), "views.cameracheck", "Error")

        return JsonResponse({'statusInfo': {
            'message': '更新摄像头人数失败!',
        }},
            status=400)

    # 检查时间问题，可能修改预约状态；
    appointments = Appoint.objects.not_canceled().filter(
        Q(Astart__lte=now_time) & Q(Afinish__gte=now_time)
        & Q(Room_id=rid))  # 只选取状态在1，2之间的预约

    if len(appointments):  # 如果有，只能有一个预约
        content = appointments[0]
        if room.Rid == "B107B":
            # 107b的监控不太靠谱，正下方看不到
            num_need = min(max(GLOBAL_INFO.today_min, num_need - 2), num_need)
        elif room.Rid == "B217":
            # 地下室关灯导致判定不清晰，晚上更严重
            if content.Astart.hour >= 20:
                num_need = min(max(GLOBAL_INFO.today_min, num_need - 2), num_need)
            else:
                num_need = min(max(GLOBAL_INFO.today_min, num_need - 1), num_need)
        if content.Atime.date() == content.Astart.date():
            # 如果预约时间在使用时间的24h之内 则人数下限为2
            num_need = min(GLOBAL_INFO.today_min, num_need)
        if content.Atemp_flag:
            # 如果为临时预约 则人数下限为1 不作为合格标准 只是记录
            num_need = min(GLOBAL_INFO.temporary_min, num_need)
        try:
            if room.Rid in {"B109A", "B207"}:  # 康德报告厅&小舞台 不考虑违约
                content.Astatus = Appoint.Status.CONFIRMED
                content.save()
            else:  # 其他房间

                # added by wxy
                # 检查人数：采样、判断、更新
                # 人数在finishappoint中检查
                # modified by pht - 2021/8/15
                # 增加UNSAVED状态
                # 逻辑是尽量宽容，因为一分钟只记录两次，两次随机大概率只有一次成功
                # 所以没必要必须随机成功才能修改错误结果
                rand = random.uniform(0, 1)
                camera_lock.acquire()
                with transaction.atomic():
                    if now_time.minute != room_previous_check_time.minute or\
                            content.Acheck_status == Appoint.Check_status.UNSAVED:
                        # 说明是新的一分钟或者本分钟还没有记录
                        # 如果随机成功，记录新的检查结果
                        if rand < GLOBAL_INFO.check_rate:
                            content.Acheck_status = Appoint.Check_status.FAILED
                            content.Acamera_check_num += 1
                            if temp_stu_num >= num_need:  # 如果本次检测合规
                                content.Acamera_ok_num += 1
                                content.Acheck_status = Appoint.Check_status.PASSED
                        # 如果随机失败，锁定上一分钟的结果
                        else:
                            if content.Acheck_status == Appoint.Check_status.FAILED:
                                # 如果本次检测合规，宽容时也算上一次通过（因为一分钟只检测两次）
                                if temp_stu_num >= num_need:
                                    content.Acamera_ok_num += 1
                            # 本分钟暂无记录
                            content.Acheck_status = Appoint.Check_status.UNSAVED
                    else:
                        # 和上一次检测在同一分钟，此时：1.不增加检测次数 2.如果合规则增加ok次数
                        if content.Acheck_status == Appoint.Check_status.FAILED:
                            # 当前不合规；如果这次检测合规，那么认为本分钟合规
                            if temp_stu_num >= num_need:
                                content.Acamera_ok_num += 1
                                content.Acheck_status = Appoint.Check_status.PASSED
                        # else:当前已经合规，不需要额外操作
                    content.save()
                camera_lock.release()
                # add end
        except Exception as e:
            operation_writer(SYSTEM_LOG, "预约"+str(content.Aid) +
                             "更新摄像头人数失败2: "+str(e), "views.cameracheck", "Error")

            return JsonResponse({'statusInfo': {
                'message': '更新预约状态失败!',
            }},
                status=400)
        try:
            if now_time > content.Astart + timedelta(
                    minutes=15) and content.Astatus == Appoint.Status.APPOINTED:
                status, tempmessage = set_appoint_reason(
                    content, Appoint.Reason.R_LATE)
                # 该函数只是把appoint标记为迟到(填写reason)并修改状态为进行中，不发送微信提醒
                if not status:
                    operation_writer(SYSTEM_LOG, "预约"+str(content.Aid) +
                                     "设置为迟到时的返回值异常 "+tempmessage, "views.cameracheck", "Error")
        except Exception as e:
            operation_writer(SYSTEM_LOG, "预约"+str(content.Aid) +
                             "在迟到状态设置过程中: "+tempmessage, "views.cameracheck", "Error")
            # added by wxy: 违约原因:迟到
            # status, tempmessage = appoint_violate(
            #     content, Appoint.Reason.R_LATE)
            # if not status:
            #     operation_writer(SYSTEM_LOG, "预约"+str(content.Aid) +
            #                      "因迟到而违约,返回值出现异常: "+tempmessage, "views.cameracheck", "Error")
        # except Exception as e:
        #     operation_writer(SYSTEM_LOG, "预约"+str(content.Aid) +
        #                      "在迟到违约过程中: "+tempmessage, "views.cameracheck", "Error")

        return JsonResponse({}, status=200)  # 返回空就好
    else:  # 否则的话 相当于没有预约 正常返回
        return JsonResponse({}, status=200)  # 返回空就好


@require_POST
@csrf_exempt
@identity_check(redirect_field_name='origin')
def cancelAppoint(request):
    context = {}
    try:
        Aid = request.POST.get('cancel_btn')
        appoints = Appoint.objects.filter(Astatus=Appoint.Status.APPOINTED)
        appoint = appoints.get(Aid=Aid)
    except:
        return redirect(message_url(
            wrong("预约不存在、已经开始或者已取消!"),
            reverse("Appointment:admin_index")))

    try:
        # TODO: major_sid
        Pid = request.user.username
        assert appoint.major_student.Sid_id == Pid
    except:
        return redirect(message_url(
            wrong("请不要恶意尝试取消不是自己发起的预约!"),
            reverse("Appointment:admin_index")))

    if (GLOBAL_INFO.restrict_cancel_time
            and appoint.Astart < datetime.now() + timedelta(minutes=30)):
        return redirect(message_url(
            wrong("不能取消开始时间在30分钟之内的预约!"),
            reverse("Appointment:admin_index")))

    with transaction.atomic():
        appoint_room_name = appoint.Room.Rtitle
        appoint.cancel()
        scheduler_func.cancel_scheduler(appoint.Aid, "Problem")

        # TODO: major_sid
        operation_writer(appoint.major_student.Sid_id,
                               f"取消了预约{appoint.Aid}",
                               "scheduler_func.cancelAppoint", "OK")
        succeed("成功取消对" + appoint_room_name + "的预约!", context)
        print('will send cancel message')
        scheduler_func.set_cancel_wechat(appoint)

    return redirect(message_url(context, reverse("Appointment:admin_index")))


@csrf_exempt
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
        if display_token != GLOBAL_INFO.display_token:
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


# modified by wxy
@identity_check(redirect_field_name='origin')
def admin_index(request):   # 我的账户也主函数

    render_context = {}
    render_context.update(
        login_url=GLOBAL_INFO.login_url,
        show_admin=(request.user.is_superuser or request.user.is_staff),
    )

    my_messages.transfer_message_context(request.GET, render_context,
                                         normalize=True)

    # 学生基本信息
    Pid = request.user.username
    my_info = web_func.get_user_info(Pid)
    participant = get_participant(Pid)
    if participant.agree_time is not None:
        my_info['agree_time'] = str(participant.agree_time)

    # 头像信息
    img_path = get_avatar(request.user)
    render_context.update(my_info=my_info, img_path=img_path)

    # 分成两类,past future
    # 直接从数据库筛选两类预约
    appoint_list_future = web_func.get_appoints(Pid, 'future').get('data')
    appoint_list_past = web_func.get_appoints(Pid, 'past').get('data')

    for x in appoint_list_future:
        x['Astart_hour_minute'] = datetime.strptime(
            x['Astart'], "%Y-%m-%dT%H:%M:%S").strftime("%I:%M %p")
        x['Afinish_hour_minute'] = datetime.strptime(
            x['Afinish'], "%Y-%m-%dT%H:%M:%S").strftime("%I:%M %p")
        appoint = Appoint.objects.get(Aid=x['Aid'])
        # TODO: major_sid
        major_id = str(appoint.major_student.Sid_id)
        x['check_major'] = (Pid == major_id)

    for x in appoint_list_past:
        x['Astart_hour_minute'] = datetime.strptime(
            x['Astart'], "%Y-%m-%dT%H:%M:%S").strftime("%I:%M %p")
        x['Afinish_hour_minute'] = datetime.strptime(
            x['Afinish'], "%Y-%m-%dT%H:%M:%S").strftime("%I:%M %p")

    appoint_list_future.sort(key=lambda k: k['Astart'])
    appoint_list_past.sort(key=lambda k: k['Astart'])
    appoint_list_past.reverse()
    render_context.update(appoint_list_future=appoint_list_future,
                          appoint_list_past=appoint_list_past)

    return render(request, 'Appointment/admin-index.html', render_context)


# modified by wxy
@identity_check(redirect_field_name='origin')
def admin_credit(request):

    render_context = {}
    render_context.update(
        login_url=GLOBAL_INFO.login_url,
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

    vio_list = web_func.get_appoints(
        Pid, 'violate', major=True, to_json=False).get('data')

    if request.method == 'POST' and request.POST:
        if request.POST.get('feedback') is not None:
            # 申诉反馈
            # TODO: 检查合法性 添加信息 查询已有反馈并跳转
            return redirect(GLOBAL_INFO.login_url.rstrip('/') + '/feedback/')

    vio_list_display = web_func.appoints2json(vio_list)
    for x, appoint in zip(vio_list_display, vio_list):
        x['Astart_hour_minute'] = appoint.Astart.strftime("%I:%M %p")
        x['Afinish_hour_minute'] = appoint.Afinish.strftime("%I:%M %p")
    render_context.update(vio_list=vio_list_display)
    return render(request, 'Appointment/admin-credit.html', render_context)


# added by wxy
# modified by dyh
@csrf_exempt
def door_check(request):  # 先以Sid Rid作为参数，看之后怎么改

    # --------- 基本信息 --------- #

    Sid, Rid = request.GET.get("Sid", None), request.GET.get("Rid", None)
    student, room, now_time, min15 = None, None, datetime.now(), timedelta(minutes=15)
    try:
        student = get_participant(Sid, raise_except=True)
        all_Rid = [room.Rid for room in Room.objects.all()]
        Rid = doortoroom(Rid)
        if Rid[:4] in all_Rid:  # 表示增加了一个未知的A\B号
            Rid = Rid[:4]
        room = Room.objects.get(Rid=Rid)
    except:
        user = student or None  # TODO: 设置默认刷卡记录者
        cardcheckinfo_writer(user, room, False, False,
                             f"学号{Sid}或房间号{Rid}错误")
        return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

    # --------- 直接进入 --------- #

    if room.Rstatus == Room.Status.FORBIDDEN:   # 禁止使用的房间
        cardcheckinfo_writer(student, room, False, False, f"刷卡拒绝：禁止使用")
        return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

    if room.RneedAgree:
        if student.agree_time is None:
            cardcheckinfo_writer(student, room, False, False, f"刷卡拒绝：未签署协议")
            send_wechat_message(
                stuid_list=[Sid],
                start_time=datetime.now(),
                room=room,
                message_type="need_agree",
                major_student=student,
                usage="刷卡开门",
                announcement="",
                num=1,
                reason='',
                url='/agreement',
            )
            return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

    if room.Rstatus == Room.Status.UNLIMITED:   # 自习室

        if room.RIsAllNight:  # 通宵自习室
            cardcheckinfo_writer(student, room, True, True, f"刷卡开门：通宵自习室")
            return JsonResponse({"code": 0, "openDoor": "true"}, status=200)

        else:  # 不是通宵自习室

            # 考虑到次晨的情况，判断一天内的时段
            now = timedelta(hours=now_time.hour, minutes=now_time.minute)
            start = timedelta(hours=room.Rstart.hour, minutes=room.Rstart.minute)
            finish = timedelta(hours=room.Rfinish.hour,
                               minutes=room.Rfinish.minute)

            if (now >= min(start, finish) and now <= max(start, finish)) ^ (start > finish):   # 在开放时间内
                cardcheckinfo_writer(student, room, True, True, f"刷卡开门：自习室")
                return JsonResponse({"code": 0, "openDoor": "true"}, status=200)

            else:  # 不在开放时间内
                cardcheckinfo_writer(student, room, False,
                                     False, f"刷卡拒绝：自习室不开放")
            return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

    # --------- 预约进入 --------- #

    # 获取房间的预约
    room_appoint = Appoint.objects.not_canceled().filter(   # 只选取接下来15分钟进行的预约
        Astart__lte=now_time + min15, Afinish__gte=now_time, Room_id=Rid)

    # --- modify by dyh: 更改规则 --- #
    # --- modify by lhw: 临时预约 --- #

    if len(room_appoint) != 0:  # 当前有预约

        if len(room_appoint.filter(students__in=[student])) == 0:   # 不是自己的预约
            cardcheckinfo_writer(student, room, False, False, f"刷卡拒绝：该房间有别人的预约，或者距离别人的下一条预约开始不到15min！")
            return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

        else:   # 自己的预约
            cardcheckinfo_writer(student, room, True, True, f"刷卡开门：预约进入")
            return JsonResponse({"code": 0, "openDoor": "true"}, status=200)

    else:   # 当前无预约

        if check_temp_appoint(room) == False:   # 房间不可以临时预约
            cardcheckinfo_writer(student, room, False, False, f"刷卡拒绝：该房间不可临时预约")
            return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

        else:   # 该房间可以用于临时预约

            # 注意，由于制度上不允许跨天预约，这里的逻辑也不支持跨日预约（比如从晚上23:00约到明天1:00）。
            start = datetime(now_time.year, now_time.month, now_time.day,
                             now_time.hour, now_time.minute, 0)  # 需要剥离秒级以下的数据，否则admin-index无法正确渲染
            timeid = web_func.get_time_id(room, time(start.hour, start.minute))

            finish, valid = web_func.get_hour_time(room, timeid + 1)
            finish = datetime(now_time.year, now_time.month, now_time.day, int(
                finish.split(':')[0]), int(finish.split(':')[1]), 0)

            # 房间未开放
            if timeid < 0 or not valid:
                message = f"该时段房间未开放！别熬夜了，回去睡觉！"
                cardcheckinfo_writer(student, room, False,
                                     False, f"刷卡拒绝：临时预约失败（{message}）")
                send_wechat_message(
                    [Sid], start, room, "temp_appointment_fail", student, "临时预约", "", 1, message)
                return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

            # 检查时间是否合法
            # 合法条件：为避免冲突，临时预约时长必须超过15分钟；预约时在房间可用时段
            # OBSELETE: 时间合法（暂时将间隔定为5min）
            if valid:
                contents = {
                    'Rid': Rid,
                    'students': [Sid],
                    'Sid': Sid,
                    'Astart': start,
                    'Afinish': finish,
                    'non_yp_num': 0,
                    'Ausage': "临时预约",
                    'announcement': "",
                    'Atemp_flag': True
                }
                response = scheduler_func.addAppoint(contents)

                if response.status_code == 200:  # 临时预约成功
                    cardcheckinfo_writer(
                        student, room, True, True, f"刷卡开门：临时预约")
                    return JsonResponse({"code": 0, "openDoor": "true"}, status=200)

                else:   # 无法预约（比如没信用分了）
                    message = json.loads(response.content)[
                        "statusInfo"]["message"]
                    cardcheckinfo_writer(
                        student, room, False, False, f"刷卡拒绝：临时预约失败（{message}）")
                    send_wechat_message(
                        [Sid], start, room, "temp_appointment_fail", student, "临时预约", "", 1, message)
                    return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

            else:   # 预约时间不合法
                message = f"预约时间不合法，请不要恶意篡改数据！"
                cardcheckinfo_writer(student, room, False,
                                     False, f"刷卡拒绝：临时预约失败（{message}）")
                send_wechat_message(
                    [Sid], start, room, "temp_appointment_fail", student, "临时预约", "", 1, message)
                return JsonResponse({"code": 1, "openDoor": "false"}, status=400)

    # --- modify end (2021.7.10) --- #
    # --- modify end (2021.8.16) --- #

    # try:
    #     with transaction.atomic():
    #         for now_appoint in stu_appoint:
    #             if (now_appoint.Astatus == Appoint.Status.APPOINTED and datetime.now() <=
    #                     now_appoint.Astart + timedelta(minutes=15)):
    #                 now_appoint.Astatus = Appoint.Status.PROCESSING
    #                 now_appoint.save()
    # except Exception as e:
    #     operation_writer(SYSTEM_LOG,
    #                      "可以开门却不开门的致命错误，房间号为" +
    #                      str(Rid) + ",学生为"+str(Sid)+",错误为:"+str(e),
    #                      "views.doorcheck",
    #                      "Error")
    #     cardcheckinfo_writer(student, room, False, True)
    #     return JsonResponse(  # 未知错误
    #         {
    #             "code": 1,
    #             "openDoor": "false",
    #         },
    #         status=400)


@csrf_exempt
@identity_check(redirect_field_name='origin', auth_func=lambda x: True)
def index(request):  # 主页
    render_context = {}
    render_context.update(
        login_url=GLOBAL_INFO.login_url,
        show_admin=(request.user.is_superuser or request.user.is_staff),
    )
    # 处理学院公告
    if (College_Announcement.objects.all()):
        try:
            message_item = College_Announcement.objects.get(
                show=College_Announcement.Show_Status.Yes)
            render_context.update(message_code=1, show_message=message_item.announcement)
            # 必定只有一个才能继续
        except:
            render_context.update(message_code=0)
            # print("无法顺利呈现公告，原因可能是没有将状态设置为YES或者超过一条状态被设置为YES")

    # 获取可能的全局消息
    my_messages.transfer_message_context(request.GET, render_context, normalize=True)


    #--------- 前端变量 ---------#

    room_list = Room.objects.all()
    now, tomorrow = datetime.now(), datetime.today() + timedelta(days=1)
    occupied_rooms = Appoint.objects.not_canceled().filter(
        Astart__lte=now + timedelta(minutes=15), Afinish__gte=now).values('Room')   # 接下来有预约的房间
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

    #--------- 1,2 地下室状态部分 ---------#

    double_list = ['航模', '绘画', '书法', '活动']
    function_room_title_query = ~Q(Rtitle__icontains="研讨")
    function_room_title_query |= Q(Rtitle__icontains="/")
    for room_title in double_list:
        function_room_title_query |= Q(Rtitle__icontains=room_title)
    function_room_list = room_list.exclude(Rid__icontains="R").filter(
        function_room_title_query,
        Rstatus=Room.Status.PERMITTED).order_by('Rid')

    #--------- 地下室状态：left tab ---------#
    suspended_room_list = room_list.filter(
        Rstatus=Room.Status.UNLIMITED).order_by('-Rtitle')                          # 开放房间
    statistics_info = [(room, (room.Rpresent * 10) // (room.Rmax or 1))
                       for room in suspended_room_list]                             # 开放房间人数统计

    #--------- 地下室状态：right tab ---------#
    talk_room_list = room_list.filter(                                              # 研讨室（展示临时预约）
        Rtitle__icontains="研讨",
        Rstatus=Room.Status.PERMITTED).order_by('Rid')
    room_info = [(room, {'Room': room.Rid} in occupied_rooms, format_time(          # 研讨室占用情况
        room_appointments[room.Rid])) for room in talk_room_list]

    #--------- 3 俄文楼部分 ---------#

    russian_room_list = room_list.filter(Rstatus=Room.Status.PERMITTED).filter(     # 俄文楼
        Rid__icontains="R").order_by('Rid')
    russ_len = len(russian_room_list)

    render_context.update(
        function_room_list=function_room_list,
        statistics_info=statistics_info,
        talk_room_list=talk_room_list, room_info=room_info,
        russian_room_list=russian_room_list, russ_len=russ_len,
    )

    if request.method == "POST":

        # YHT: added for Russian search
        request_time = request.POST.get("request_time", None)
        russ_request_time = request.POST.get("russ_request_time", None)
        check_type = ""
        if request_time is None and russ_request_time is not None:
            check_type = "russ"
            request_time = russ_request_time
        elif request_time is not None and russ_request_time is None:
            check_type = "talk"
        else:
            return render(request, 'Appointment/index.html', render_context)

        if request_time != None and request_time != "":  # 初始加载或者不选时间直接搜索则直接返回index页面，否则进行如下反查时间
            day, month, year = int(request_time[:2]), int(
                request_time[3:5]), int(request_time[6:10])
            re_time = datetime(year, month, day)  # 获取目前request时间的datetime结构
            if re_time.date() < datetime.now().date():  # 如果搜过去时间
                render_context.update(search_code=1,
                                      search_message="请不要搜索已经过去的时间!")
                return render(request, 'Appointment/index.html', render_context)
            elif re_time.date() - datetime.now().date() > timedelta(days=6):
                # 查看了7天之后的
                render_context.update(search_code=1,
                                      search_message="只能查看最近7天的情况!")
                return render(request, 'Appointment/index.html', render_context)
            # 到这里 搜索没问题 进行跳转
            urls = my_messages.append_query(
                reverse("Appointment:arrange_talk"),
                year=year, month=month, day=day, type=check_type)
            # YHT: added for Russian search
            return redirect(urls)

    return render(request, 'Appointment/index.html', render_context)


@csrf_exempt
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
                reverse("Appointment:admin_index")))
        except:
            my_messages.wrong('签署失败，请重试！', render_context)
    elif request.method == 'POST':
        return redirect(reverse("Appointment:index"))
    if participant.agree_time is not None:
        render_context.update(agree_time=str(participant.agree_time))
    return render(request, 'Appointment/agreement.html', render_context)


@identity_check(redirect_field_name='origin')
def arrange_time(request):
    if request.method == 'GET':
        try:
            Rid = request.GET.get('Rid')
            print("Rid,", Rid, ",type,", type(Rid))
            check = Room.objects.filter(Rid=Rid)
            if not len(check):
                return redirect(reverse('Appointment:index'))
            room_object = check[0]

        except:
            return redirect(reverse('Appointment:index'))

    dayrange_list = web_func.get_dayrange()

    if room_object.Rstatus == Room.Status.FORBIDDEN:
        return render(request, 'Appointment/booking.html', locals())

    else:
        # 观察总共有多少个时间段
        time_range = web_func.get_time_id(
            room_object, room_object.Rfinish, mode="leftopen")
        for day in dayrange_list:  # 对每一天 读取相关的展示信息
            day['timesection'] = []
            temp_hour, temp_minute = room_object.Rstart.hour, int(
                room_object.Rstart.minute >= 30)

            for i in range(time_range + 1):  # 对每半个小时
                timesection = {}
                timesection['starttime'] = str(
                    temp_hour + (i + temp_minute) // 2).zfill(2) + ":" + str(
                    (i + temp_minute) % 2 * 30).zfill(2)
                timesection['status'] = 0  # 0可用 1已经预约 2已过
                timesection['id'] = i
                day['timesection'].append(timesection)
        # 筛选可能冲突的预约
        appoints = Appoint.objects.not_canceled().filter(
            Room_id=Rid,
            Afinish__gte=datetime(year=dayrange_list[0]['year'],
                                  month=dayrange_list[0]['month'],
                                  day=dayrange_list[0]['day'],
                                  hour=0,
                                  minute=0,
                                  second=0),
            Astart__lte=datetime(year=dayrange_list[-1]['year'],
                                 month=dayrange_list[-1]['month'],
                                 day=dayrange_list[-1]['day'],
                                 hour=23,
                                 minute=59,
                                 second=59))

        for appoint_record in appoints:
            change_id_list = web_func.timerange2idlist(Rid, appoint_record.Astart,
                                                       appoint_record.Afinish, time_range)
            appoint_usage = html.escape(appoint_record.Ausage).replace('\n', '<br/>')
            appointer_name = html.escape(appoint_record.major_student.name)
            for day in dayrange_list:
                if appoint_record.Astart.date() == date(day['year'], day['month'],
                                                        day['day']):
                    for i in change_id_list:
                        day['timesection'][i]['status'] = 1
                        day['timesection'][i]['display_info'] = '<br/>'.join([
                            f'{appoint_usage}',
                            f'预约者：{appointer_name}',
                        ])

        # 删去今天已经过去的时间
        present_time_id = web_func.get_time_id(
            room_object, datetime.now().time())
        for i in range(min(time_range, present_time_id) + 1):
            dayrange_list[0]['timesection'][i]['status'] = 1

        js_dayrange_list = json.dumps(dayrange_list)

        return render(request, 'Appointment/booking.html', locals())


@identity_check(redirect_field_name='origin')
def arrange_talk_room(request):

    try:
        assert request.method == "GET"
        year = int(request.GET.get("year"))
        month = int(request.GET.get("month"))
        day = int(request.GET.get("day"))
        # YHT: added for russian search
        check_type = str(request.GET.get("type"))
        assert check_type in {"russ", "talk"}
        re_time = datetime(year, month, day)  # 如果有bug 直接跳转
        if (re_time.date() < datetime.now().date()
                or re_time.date() - datetime.now().date() > timedelta(days=6)):
            # 这种就是乱改url
            return redirect(reverse("Appointment:index"))
        # 接下来判断时间
    except:
        return redirect(reverse("Appointment:index"))

    is_today = False
    if check_type == "talk":
        if re_time.date() == datetime.now().date():
            is_today = True
            show_min = GLOBAL_INFO.today_min
        room_list = Room.objects.filter(
            Rtitle__contains='研讨').filter(Rstatus=Room.Status.PERMITTED).order_by('Rmin', 'Rid')
    else:  # type == "russ"
        room_list = Room.objects.filter(Rstatus=Room.Status.PERMITTED).filter(
            Rid__icontains="R").order_by('Rid')
    # YHT: added for russian search
    Rids = [room.Rid for room in room_list]
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
        print("in arrange talk room，present_time_id", present_time_id)

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
                appoint_usage = html.escape(appointment.Ausage).replace('\n', '<br/>')

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


@identity_check(redirect_field_name='origin')
def check_out(request):  # 预约表单提交
    try:
        if request.method == "GET":
            Rid = request.GET.get('Rid')
            weekday = request.GET.get('weekday')
            startid = request.GET.get('startid')
            endid = request.GET.get('endid')
        else:
            Rid = request.POST.get('Rid')
            weekday = request.POST.get('weekday')
            startid = request.POST.get('startid')
            endid = request.POST.get('endid')
        # 防止恶意篡改参数
        assert weekday in wklist
        assert int(startid) >= 0
        assert int(endid) >= 0
        assert int(endid) >= int(startid)
        appoint_params = {
            'Rid': Rid,
            'weekday': weekday,
            'startid': int(startid),
            'endid': int(endid)
        }
        room_object = Room.objects.filter(Rid=Rid)[0]
        dayrange_list = web_func.get_dayrange()
        for day in dayrange_list:
            if day['weekday'] == appoint_params['weekday']:  # get day
                appoint_params['date'] = day['date']
                appoint_params['starttime'], valid = web_func.get_hour_time(
                    room_object, appoint_params['startid'])
                assert valid is True
                appoint_params['endtime'], valid = web_func.get_hour_time(
                    room_object, appoint_params['endid'] + 1)
                assert valid is True
                appoint_params['year'] = day['year']
                appoint_params['month'] = day['month']
                appoint_params['day'] = day['day']
                # 最小人数下限控制
                appoint_params['Rmin'] = room_object.Rmin
                if datetime.now().strftime("%a") == appoint_params['weekday']:
                    appoint_params['Rmin'] = min(
                        GLOBAL_INFO.today_min, room_object.Rmin)
        appoint_params['Sid'] = request.user.username
        appoint_params['Sname'] = get_participant(appoint_params['Sid']).name

    except:
        return redirect(reverse('Appointment:index'))

    # 准备上下文，此时预约的时间地点、发起人已经固定
    render_context = {}
    render_context.update(room_object=room_object, appoint_params=appoint_params)

    if request.method == 'POST':  # 提交预约信息
        contents = dict(request.POST)
        for key in contents.keys():
            if key != "students":
                contents[key] = contents[key][0]
                if key in {'year', 'month', 'day'}:
                    contents[key] = int(contents[key])
        # 处理外院人数
        if contents['non_yp_num'] == "":
            contents['non_yp_num'] = 0
        else:
            try:
                contents['non_yp_num'] = int(contents['non_yp_num'])
                assert contents['non_yp_num'] >= 0
            except:
                wrong("外院人数有误,请按要求输入!", render_context)
        # 处理用途未填写
        if contents['Ausage'] == "":
            wrong("请输入房间用途!", render_context)
        # 处理单人预约
        if "students" not in contents.keys():
            contents['students'] = [contents['Sid']]
        else:
            contents['students'].append(contents['Sid'])

        contents['Astart'] = datetime(contents['year'], contents['month'],
                                      contents['day'],
                                      int(contents['starttime'].split(":")[0]),
                                      int(contents['starttime'].split(":")[1]),
                                      0)
        contents['Afinish'] = datetime(contents['year'], contents['month'],
                                       contents['day'],
                                       int(contents['endtime'].split(":")[0]),
                                       int(contents['endtime'].split(":")[1]),
                                       0)
        if my_messages.get_warning(render_context)[0] is None:
            # 增加contents内容，这里添加的预约需要所有提醒，所以contents['new_require'] = 1
            contents['new_require'] = 1
            response = scheduler_func.addAppoint(
                contents)  # 否则没必要执行

            if response.status_code == 200:  # 成功预约
                return redirect(message_url(
                    succeed(f"预约{room_object.Rtitle}成功!"),
                    reverse("Appointment:admin_index")))
            else:
                add_dict = json.loads(response.content)['statusInfo']
                wrong(add_dict['message'], render_context)

    js_stu_list = web_func.get_student_chosen_list(request)
    member_id_set = set(get_member_ids(request.user))
    for js_stu in js_stu_list:
        if js_stu['id'] in member_id_set:
            js_stu['text'] += '_成员'
    render_context.update(js_stu_list=js_stu_list)

    if request.method == 'POST':
        # 到这里说明预约失败 补充一些已有信息,避免重复填写
        selected_stu_list = [
            w for w in js_stu_list if w['id'] in contents['students']]
        no_clause = True
        render_context.update(selected_stu_list=selected_stu_list,
                              no_clause=no_clause)
    return render(request, 'Appointment/checkout.html', render_context)


def logout(request):    # 登出系统
    auth.logout(request)
    return redirect(reverse('Appointment:index'))


########################################
# for 年度总结
########################################

@csrf_exempt
@identity_check(redirect_field_name='origin')
def summary(request):  # 主页
    Pid = ""

    try:
        if not Pid:
            Pid = request.user.username
        with open(f'Appointment/summary_info/{Pid}.txt','r',encoding='utf-8') as fp:
            myinfo = json.load(fp)
    except:
        return redirect(reverse("Appointment:logout"))

    Rid_list = {room.Rid: room.Rtitle.split('(')[0] for room in Room.objects.all()}

    # page 0
    Sname = myinfo['Sname']

    # page 1
    all_appoint_num = 12649
    all_appoint_len = 19268.17
    all_appoint_len_day = round(all_appoint_len/24)

    # page 2
    appoint_make_num = int(myinfo['appoint_make_num'])
    appoint_make_num_pct = myinfo['rank_num']
    appoint_make_hour = round(myinfo['appoint_make_hour'], 2)
    appoint_make_hour_pct = myinfo['rank_hour']
    appoint_attend_num = int(myinfo['appoint_attend_num'])
    appoint_attend_hour = round(myinfo['appoint_attend_hour'], 2)

    # page 3
    hottest_room_1 = ['B214', Rid_list['B214'], 1952]
    hottest_room_2 = ['B220', Rid_list['B220'], 1715]
    hottest_room_3 = ['B221', Rid_list['B221'], 1661]

    # page 4
    Sfav_room_id = myinfo['favourite_room_id']
    if Sfav_room_id:
        Sfav_room_name = Rid_list[Sfav_room_id]
        Sfav_room_freq = int(myinfo['favourite_room_freq'])

    # page 5
    Smake_time_most = myinfo['make_time_most']
    if Smake_time_most:
        Smake_time_most = int(Smake_time_most)

    try:
        Suse_time_list = myinfo['use_time_list'].split(';')
    except:
        Suse_time_list = [0]*24
    Suse_time_list = list(map(lambda x: int(x), Suse_time_list))
    try:
        Suse_time_most = Suse_time_list.index(max(Suse_time_list))
    except:
        Suse_time_most = -1
    Suse_time_list_js = json.dumps(Suse_time_list[6:])
    Suse_time_list_label = [str(i) for i in range(6, 24)]
    Suse_time_list_label_js = json.dumps(Suse_time_list_label)

    # page 6
    Sfirst_appoint = myinfo['first_appoint']
    if Sfirst_appoint:
        Sfirst_appoint = Sfirst_appoint.split('|')
        Sfirst_appoint.append(Rid_list[Sfirst_appoint[4]])

    # page 7
    Skeywords = myinfo['usage']
    if Skeywords:
        Skeywords = Skeywords.split('|')
        Skeywords_for_len = Skeywords.copy()
        if '' in Skeywords_for_len:
            Skeywords_for_len.remove('')
        Skeywords_len = len(Skeywords_for_len)
    else:
        Skeywords_len = 0

    # page 8
    Sfriend = myinfo['friend']
    if Sfriend == '':
        Sfriend = None
    if Sfriend:
        Sfriend = Sfriend.split(';')

    # page 9 熬夜冠军
    aygj = myinfo['aygj']
    if aygj:
        aygj = aygj.split('|')
        aygj_num = 80

    # page 10 早起冠军
    zqgj = myinfo['zqgj']
    if zqgj:
        zqgj = zqgj.split('|')
        # print(zqgj)
        zqgj.insert(6, Rid_list[zqgj[5]])
        zqgj_num = 109

    # page 11 未雨绸缪
    wycm = myinfo['wycm']
    wycm_num = 44

    # page 12 极限操作
    jxcz = myinfo['jxcz']
    if jxcz:
        jxcz = jxcz.split('|')
        jxcz.insert(6, Rid_list[jxcz[5]])
        jxcz_num = 102

    # page 13 元培鸽王
    ypgw = myinfo['ypgw']
    ypgw_num = 22

    # page 14 新功能预告
    return render(request, 'Appointment/summary.html', locals())
