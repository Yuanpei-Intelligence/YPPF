# YWolfeee:
# 本py文件保留所有需要与scheduler交互的函数。
from Appointment import global_info
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job


from Appointment.models import Participant, Room, Appoint, College_Announcement
from django.http import JsonResponse, HttpResponse  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库
import Appointment.utils.utils as utils
import Appointment.utils.web_func as web_func
from Appointment.utils.identity import get_participant

'''
YWolfeee:
scheduler_func.py是所有和scheduler定时任务发生交互的函数集合。
本py文件中的所有函数，或者发起了一个scheduler任务，或者删除了一个scheduler任务。
这些函数大多对应预约的开始、结束，微信的定时发送等。
如果需要实现新的函数，建议先详细阅读本py中其他函数的实现方式。
'''

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")


# 每周清除预约的程序，会写入logstore中
@register_job(scheduler, 'cron', id='ontime_delete', day_of_week='sat', hour='3', minute="30", second='0', replace_existing=True)
def clear_appointments():
    if global_info.delete_appoint_weekly:   # 是否清除一周之前的预约
        appoints_to_delete = Appoint.objects.filter(
            Afinish__lte=datetime.now()-timedelta(days=7))
        try:
            # with transaction.atomic(): //不采取原子操作
            utils.write_before_delete(appoints_to_delete)  # 删除之前写在记录内
            appoints_to_delete.delete()
        except Exception as e:
            utils.operation_writer(global_info.system_log, "定时删除任务出现错误: "+str(e),
                             "scheduler_func.clear_appointments", "Problem")

        # 写入日志
        utils.operation_writer(global_info.system_log, "定时删除任务成功", "scheduler_func.clear_appointments")


def set_scheduler(appoint):
    '''不负责发送微信,不处理已经结束的预约,不处理始末逆序的预约,可以任何时间点调用,应该不报错'''
    # --- written by pht: 统一设置预约定时任务 --- #
    start = appoint.Astart
    finish = appoint.Afinish
    current_time = datetime.now() + timedelta(seconds=5)
    if finish < start:          # 开始晚于结束，预约不合规
        utils.operation_writer(
                                global_info.system_log,
                                f'预约{appoint.Aid}时间为{start}<->{finish}，未能设置定时任务',
                                'scheduler_func.set_scheduler',
                                'Error'
                                )
        return False            # 直接返回，预约不需要设置
    if finish < current_time:   # 预约已经结束
        utils.operation_writer(
                                global_info.system_log,
                                f'预约{appoint.Aid}在设置定时任务时已经结束',
                                'scheduler_func.set_scheduler',
                                'Error'
                                )
        return False            # 直接返回，预约不需要设置
    has_started = start < current_time
    if has_started:             # 临时预约或特殊情况下设置任务时预约可能已经开始
        start = current_time    # 改为立刻执行
    # --- written end (2021.8.31) --- #

    # written by dyh: 在Astart将状态变为PROCESSING
    if not (has_started and appoint.Astatus == Appoint.Status.PROCESSING):
        scheduler.add_job(web_func.startAppoint,
                            args=[appoint.Aid],
                            id=f'{appoint.Aid}_start',
                            replace_existing=True,
                            next_run_time=start)

    # write by cdf start2  # 添加定时任务：finish
    scheduler.add_job(web_func.finishAppoint,
                        args=[appoint.Aid],
                        id=f'{appoint.Aid}_finish',
                        replace_existing=True,
                        next_run_time=finish)
    return True


def cancel_scheduler(appoint_or_aid):  # models.py中使用
    '''
    noexcept
    逻辑是finish标识预约是否终止,未终止时才取消其它定时任务
    '''
    # --- modify by pht: 统一设置预约定时任务 --- #
    if isinstance(appoint_or_aid, Appoint):
        aid = appoint_or_aid.Aid
    else:
        aid = appoint_or_aid
    try:
        scheduler.remove_job(f'{aid}_finish')
        try:
            scheduler.remove_job(f'{aid}_start')
        except:pass
        try:
            scheduler.remove_job(f'{aid}_start_wechat')
        except:pass
        return JsonResponse({'statusInfo': {
            'message': '删除成功!',
        }},
            json_dumps_params={'ensure_ascii': False},
            status=200)
    except:
        return JsonResponse({'statusInfo': {
            'message': '删除计划不存在!',
        }},
            json_dumps_params={'ensure_ascii': False},
            status=400)


def cancelFunction(request):  # 取消预约
    
    warn_code = 0
    try:
        Aid = request.POST.get('cancel_btn')
        appoints = Appoint.objects.filter(Astatus=Appoint.Status.APPOINTED)
        appoint = appoints.get(Aid=Aid)
    except:
        warn_code = 1
        warning = "预约不存在、已经开始或者已取消!"
        # return render(request, 'Appointment/admin-index.html', locals())
        return redirect(
            reverse("Appointment:admin_index") + "?warn_code=" +
            str(warn_code) + "&warning=" + warning)

    try:
        # TODO: major_sid
        Pid = request.user.username
        assert appoint.major_student.Sid_id == Pid
    except:
        warn_code = 1
        warning = "请不要恶意尝试取消不是自己发起的预约！"
        # return render(request, 'Appointment/admin-index.html', locals())
        return redirect(
            reverse("Appointment:admin_index") + "?warn_code=" +
            str(warn_code) + "&warning=" + warning)

    RESTRICT_CANCEL_TIME = False
    if RESTRICT_CANCEL_TIME and appoint.Astart < datetime.now() + timedelta(minutes=30):
        warn_code = 1
        warning = "不能取消开始时间在30分钟之内的预约!"
        return redirect(
            reverse("Appointment:admin_index") + "?warn_code=" +
            str(warn_code) + "&warning=" + warning)
    # 先准备发送人
    stuid_list = list(appoint.students.values_list('Sid', flat=True))
    with transaction.atomic():
        appoint_room_name = appoint.Room.Rtitle
        appoint.cancel()
        try:
            scheduler.remove_job(f'{appoint.Aid}_finish')
        except:
            utils.operation_writer(global_info.system_log, "预约"+str(appoint.Aid) +
                             "取消时发现不存在计时器", 'scheduler_func.cancelAppoint', "Problem")
        try:
            scheduler.remove_job(f'{appoint.Aid}_start')
        except:
            utils.operation_writer(global_info.system_log, "预约"+str(appoint.Aid) +
                "取消时未发现开始计时器，可能已经开始", 'scheduler_func.cancelAppoint', "Problem")
        
        # TODO: major_sid
        utils.operation_writer(appoint.major_student.Sid_id, "取消了预约" +
                         str(appoint.Aid), "scheduler_func.cancelAppoint", "OK")
        warn_code = 2
        warning = "成功取消对" + appoint_room_name + "的预约!"
    # TODO: major_sid
    # send_status, err_message = utils.send_wechat_message([appoint.major_student.Sid_id],appoint.Astart,appoint.Room,"cancel")
    # todo: to all
        print('will send cancel message')
        scheduler.add_job(utils.send_wechat_message,
                          args=[stuid_list,
                                appoint.Astart,
                                appoint.Room,
                                "cancel",
                                appoint.major_student.name,
                                appoint.Ausage,
                                appoint.Aannouncement,
                                appoint.Anon_yp_num+appoint.Ayp_num,
                                '',
                                #appoint.major_student.credit,
                                ],
                          id=f'{appoint.Aid}_cancel_wechat',
                          next_run_time=datetime.now() + timedelta(seconds=5))
    '''
    if send_status == 1:
        # 记录错误信息
        utils.operation_writer(global_info.system_log, "预约" +
                             str(appoint.Aid) + "取消时向微信发消息失败，原因："+err_message, "scheduler_func.addAppoint", "Problem")
    '''

    # cancel wechat scheduler
    try:
        scheduler.remove_job(f'{appoint.Aid}_start_wechat')
    except:
        utils.operation_writer(global_info.system_log, "预约"+str(appoint.Aid) +
                         "取消时发现不存在wechat计时器，但也可能本来就没有", 'scheduler_func.cancelAppoint', "OK")

    return redirect(
        reverse("Appointment:admin_index") + "?warn_code=" + str(warn_code) +
        "&warning=" + warning)


# added by pht: 8.31
def set_start_wechat(appoint, students_id=None, notify_new=True):
    '''将预约成功和开始前的提醒定时发送给微信'''
    if students_id is None:
        students_id = list(appoint.students.values_list('Sid', flat=True))
    # write by cdf end2
    # modify by pht: 如果已经开始，非临时预约记录log
    if datetime.now() >= appoint.Astart:
        # add by lhw : 临时预约 # 
        if appoint.Atemp_flag == True:
            scheduler.add_job(utils.send_wechat_message,
                                args=[students_id,
                                    appoint.Astart,
                                    appoint.Room,
                                    "temp_appointment",
                                    appoint.major_student.name,
                                    appoint.Ausage,
                                    appoint.Aannouncement,
                                    appoint.Anon_yp_num+appoint.Ayp_num,
                                    '',
                                    # appoint.major_student.credit,
                                    ],
                                id=f'{appoint.Aid}_start_wechat',
                                replace_existing=True,
                                next_run_time=datetime.now() + timedelta(seconds=5))
        else:
            utils.operation_writer(global_info.system_log, "预约"+str(appoint.Aid) +
                        "尝试发送给微信时已经开始，且并非临时预约", 'scheduler_func.set_start_wechat', "Problem")
            return False
    elif datetime.now() <= appoint.Astart - timedelta(minutes=15):  # 距离预约开始还有15分钟以上，提醒有新预约&定时任务
        # print('距离预约开始还有15分钟以上，提醒有新预约&定时任务', notify_new)
        if notify_new:  # 只有在非长线预约中才添加这个job
            scheduler.add_job(utils.send_wechat_message,
                                args=[students_id,
                                    appoint.Astart,
                                    appoint.Room,
                                    "new",
                                    appoint.major_student.name,
                                    appoint.Ausage,
                                    appoint.Aannouncement,
                                    appoint.Anon_yp_num+appoint.Ayp_num,
                                    '',
                                    # appoint.major_student.credit,
                                    ],
                                id=f'{appoint.Aid}_new_wechat',
                                replace_existing=True,
                                next_run_time=datetime.now() + timedelta(seconds=5))
        scheduler.add_job(utils.send_wechat_message,
                            args=[students_id,
                                appoint.Astart,
                                appoint.Room,
                                "start",
                                appoint.major_student.name,
                                appoint.Ausage,
                                appoint.Aannouncement,
                                appoint.Ayp_num+appoint.Anon_yp_num,
                                '',
                                # appoint.major_student.credit,
                                ],
                            id=f'{appoint.Aid}_start_wechat',
                            replace_existing=True,
                            next_run_time=appoint.Astart - timedelta(minutes=15))
    else:  # 距离预约开始还有不到15分钟，提醒有新预约并且马上开始
        # send_status, err_message = utils.send_wechat_message(students_id, appoint.Astart, appoint.Room,"new&start")
        scheduler.add_job(utils.send_wechat_message,
                            args=[students_id,
                                appoint.Astart,
                                appoint.Room,
                                "new&start",
                                appoint.major_student.name,
                                appoint.Ausage,
                                appoint.Aannouncement,
                                appoint.Anon_yp_num+appoint.Ayp_num,
                                '',
                                # appoint.major_student.credit,
                                ],
                            id=f'{appoint.Aid}_start_wechat',
                            replace_existing=True,
                            next_run_time=datetime.now() + timedelta(seconds=5))
    return True


def addAppoint(contents):  # 添加预约, main function
    '''Sid: arg for `get_participant`'''

    # 检查是否为临时预约 add by lhw (2021.7.13)
    if 'Atemp_flag' not in contents.keys():
        contents['Atemp_flag'] = False
    # 首先检查房间是否存在
    try:
        room = Room.objects.get(Rid=contents['Rid'])
        assert room.Rstatus == Room.Status.PERMITTED, 'room service suspended!'
    except Exception as e:
        return JsonResponse(
            {
                'statusInfo': {
                    'message': '房间不存在或当前房间暂停预约服务,请更换房间!',
                    'detail': str(e)
                }
            },
            status=400)
    # 再检查学号对不对
    students_id = contents['students']  # 存下学号列表
    # TODO: task 0 pht 检查更新后Sid__in是否正常
    students = Participant.objects.filter(
        Sid__in=students_id).distinct()  # 获取学生objects
    try:
        assert len(students) == len(
            students_id), "students repeat or don't exists"
    except Exception as e:
        return JsonResponse(
            {
                'statusInfo': {
                    'message': '预约人信息有误,请检查后重新发起预约!',
                    'detail': str(e)
                }
            },
            status=400)

    # 检查人员信息
    try:
        #assert len(students) >= room.Rmin, f'at least {room.Rmin} students'

        # ---- modify by lhw: 加入考虑临时预约的情况 ---- #
        current_time = datetime.now()   # 获取当前时间，只获取一次，防止多次获取得到不同时间
        if current_time.date() != contents['Astart'].date():    # 若不为当天
            real_min = room.Rmin
        elif contents['Atemp_flag'] == False:                  # 当天预约，放宽限制
            real_min = min(room.Rmin, global_info.today_min)
        else:                                                   # 临时预约，放宽限制
            real_min = min(room.Rmin, global_info.temporary_min)
        # ----- modify end : 2021.7.10 ----- #

        assert len(students) + contents[
            'non_yp_num'] >= real_min, f'at least {room.Rmin} students'
    except Exception as e:
        return JsonResponse(
            {'statusInfo': {
                'message': '使用总人数需达到房间最小人数!',
                'detail': str(e)
            }},
            status=400)
    # 检查外院人数是否过多
    try:
        # assert len(
        #    students) >= contents['non_yp_num'], f"too much non-yp students!"
        assert 2 * len(
            students) >= real_min, f"too little yp students!"
    except Exception as e:
        return JsonResponse(
            {'statusInfo': {
                # 'message': '外院人数不得超过总人数的一半!',
                'message': '院内使用人数需要达到房间最小人数的一半!',
                'detail': str(e)
            }},
            status=400)

    # 检查如果是俄文楼，是否只有一个人使用
    if "R" in room.Rid:  # 如果是俄文楼系列
        try:
            assert len(
                students) + contents['non_yp_num'] == 1, f"too many people using russian room!"
        except Exception as e:
            return JsonResponse(
                {'statusInfo': {
                    'message': '俄文楼元创空间仅支持单人预约!',
                    'detail': str(e)
                }},
                status=400)

    # 检查预约时间是否正确
    try:
        #Astart = datetime.strptime(contents['Astart'], '%Y-%m-%d %H:%M:%S')
        #Afinish = datetime.strptime(contents['Afinish'], '%Y-%m-%d %H:%M:%S')
        Astart = contents['Astart']
        Afinish = contents['Afinish']
        assert Astart <= Afinish, 'Appoint time error' 

        # --- modify by lhw: Astart 可能比datetime.now小 --- #
        
        #assert Astart > datetime.now(), 'Appoint time error' 
        assert Afinish > datetime.now(), 'Appoint time error'
        
        # --- modify end: 2021.7.10 --- #

    except Exception as e:
        return JsonResponse(
            {
                'statusInfo': {
                    'message': '非法预约时间段,请不要擅自修改url!',
                    'detail': str(e)
                }
            },
            status=400)
    # 预约是否超过3小时
    try:
        assert Afinish <= Astart + timedelta(hours=3)
    except:
        return JsonResponse({'statusInfo': {
            'message': '预约时常不能超过3小时!',
        }},
            status=400)
    # 学号对了，人对了，房间是真实存在的，那就开始预约了


    # 接下来开始搜索数据库，上锁
    major_student = None    # 避免下面未声明出错
    try:
        with transaction.atomic():

            # 获取预约发起者,确认预约状态
            major_student = get_participant(contents['Sid'])
            if major_student is None:
                return JsonResponse(
                    {
                        'statusInfo': {
                            'message': '发起人信息与登录信息不符,请不要在同一浏览器同时登录不同账号!',
                        }
                    },
                    status=400)

            # 等待确认的和结束的肯定是当下时刻已经弄完的，所以不用管
            print("得到搜索列表")
            appoints = room.appoint_list.select_for_update().exclude(
                Astatus=Appoint.Status.CANCELED).filter(
                    Room_id=contents['Rid'])
            for appoint in appoints:
                start = appoint.Astart
                finish = appoint.Afinish

                # 第一种可能，开始在开始之前，只要结束的比开始晚就不行
                # 第二种可能，开始在开始之后，只要在结束之前就都不行
                if (start <= Astart < finish) or (Astart <= start < Afinish):
                    # 有预约冲突的嫌疑，但要检查一下是不是重复预约了
                    if (start == Astart and finish == Afinish
                            and appoint.Ausage == contents['Ausage']
                            and appoint.Aannouncement == contents['announcement']
                            and appoint.Ayp_num == len(students)
                            and appoint.Anon_yp_num == contents['non_yp_num']
                            and major_student == appoint.major_student):
                        # Room不用检查，肯定是同一个房间
                        # TODO: major_sid
                        utils.operation_writer(
                            major_student.Sid_id, "重复发起同时段预约，预约号"+str(appoint.Aid), "scheduler_func.addAppoint", "OK")
                        return JsonResponse({'data': appoint.toJson()}, status=200)
                    else:
                        # 预约冲突
                        return JsonResponse(
                            {
                                'statusInfo': {
                                    'message': '预约时间与已有预约冲突,请重选时间段!',
                                    'detail': appoint.toJson()
                                }
                            },
                            status=400)

            # 确认信用分符合要求
            if major_student.credit <= 0:
                return JsonResponse(
                    {'statusInfo': {
                        'message': '信用分不足,本月无法发起预约!',
                    }},
                    status=400)

            # 合法，可以返回了
            appoint = Appoint(Room=room,
                              Astart=Astart,
                              Afinish=Afinish,
                              Ausage=contents['Ausage'],
                              Aannouncement=contents['announcement'],
                              major_student=major_student,
                              Anon_yp_num=contents['non_yp_num'],
                              Ayp_num=len(students),
                              Atemp_flag=contents['Atemp_flag'])
            appoint.save()
            # appoint.students.set(students)
            for student in students:
                appoint.students.add(student)
            appoint.save()


            # modify by pht: 整合定时任务为函数
            set_scheduler(appoint)
            set_start_wechat(
                        appoint,
                        students_id=students_id,
                        notify_new=bool(contents.get('new_require', True))
                        )

            # TODO: major_sid
            utils.operation_writer(major_student.Sid_id, "发起预约，预约号" +
                             str(appoint.Aid), "scheduler_func.addAppoint", "OK")

    except Exception as e:
        utils.operation_writer(global_info.system_log, "学生" + str(major_student) +
                         "出现添加预约失败的问题:"+str(e), "scheduler_func.addAppoint", "Error")
        return JsonResponse({'statusInfo': {
            'message': '添加预约失败!请与管理员联系!',
        }},
            status=400)

    return JsonResponse({'data': appoint.toJson()}, status=200)
