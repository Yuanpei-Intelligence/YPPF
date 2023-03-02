# YWolfeee:
# 本py文件保留所有需要与scheduler交互的函数。
from datetime import datetime, timedelta

from django.http import JsonResponse
from django.db import transaction

from scheduler.scheduler import scheduler, periodical
from Appointment.config import appointment_config as CONFIG
from Appointment.models import Participant, Room, Appoint, LongTermAppoint
from Appointment.extern.constants import MessageType
from Appointment.extern.wechat import send_wechat_message
import Appointment.utils.utils as utils
import Appointment.utils.web_func as web_func
from Appointment.utils.log import write_before_delete, logger, get_user_logger
from Appointment.utils.identity import get_participant, get_auditor_ids


'''
YWolfeee:
本py文件中的所有函数，或者发起了一个scheduler任务，或者删除了一个scheduler任务。
这些函数大多对应预约的开始、结束，微信的定时发送等。
如果需要实现新的函数，建议先详细阅读本py中其他函数的实现方式。
'''


# 每周清除预约的程序，会写入logstore中
@periodical('cron', 'clear_appointments', day_of_week='sat',
            hour=3, minute=30, second=0,)
def clear_appointments():
    if CONFIG.delete_appoint_weekly:   # 是否清除一周之前的预约
        appoints_to_delete = Appoint.objects.filter(
            Afinish__lte=datetime.now()-timedelta(days=7))
        try:
            write_before_delete(appoints_to_delete)  # 删除之前写在记录内
            appoints_to_delete.delete()
        except Exception as e:
            return logger.warning(f"定时删除任务出现错误: {e}")

        # 写入日志
        logger.info("定时删除任务成功")


def set_scheduler(appoint: Appoint):
    '''不负责发送微信,不处理已经结束的预约,不处理始末逆序的预约,可以任何时间点调用,应该不报错'''
    # --- written by pht: 统一设置预约定时任务 --- #
    start = appoint.Astart
    finish = appoint.Afinish
    current_time = datetime.now() + timedelta(seconds=5)
    if finish < start:          # 开始晚于结束，预约不合规
        logger.error(f'预约{appoint.Aid}时间为{start}<->{finish}，未能设置定时任务')
        return False            # 直接返回，预约不需要设置
    if finish < current_time:   # 预约已经结束
        logger.error(f'预约{appoint.Aid}在设置定时任务时已经结束')
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


def set_appoint_wechat(appoint: Appoint, message_type: str, *extra_infos,
                       students_id=None, url=None, admin=None,
                       id=None, job_time=None):
    '''设置预约的微信提醒，默认发给所有参与者'''
    if students_id is None:
        # 先准备发送人
        students_id = list(appoint.students.values_list('Sid', flat=True))

    # 发送微信的参数
    wechat_kws = {}
    if url is not None:
        wechat_kws.update(url=url)
    if admin is not None:
        wechat_kws.update(is_admin=admin)

    # 默认立刻发送
    if job_time is None:
        job_time = datetime.now() + timedelta(seconds=5)
    # 添加定时任务的关键字参数
    add_job_kws = dict(replace_existing=True, next_run_time=job_time)
    if id is None:
        id = f'{appoint.pk}_{message_type}'
    if id is not None:
        add_job_kws.update(id=id)
    scheduler.add_job(send_wechat_message,
                      args=[
                          students_id,
                          appoint.Astart,
                          appoint.Room,
                          message_type,
                          appoint.major_student.name,
                          appoint.Ausage,
                          appoint.Aannouncement,
                          appoint.Anon_yp_num + appoint.Ayp_num,
                          *extra_infos[:1],
                      ],
                      kwargs=wechat_kws,
                      **add_job_kws)


def set_cancel_wechat(appoint: Appoint, students_id=None):
    '''取消预约的微信提醒，默认发给所有参与者'''
    set_appoint_wechat(
        appoint, MessageType.CANCELED.value,
        students_id=students_id, id=f'{appoint.Aid}_cancel_wechat')


# added by pht: 8.31
def set_start_wechat(appoint: Appoint, students_id=None, notify_create=True):
    '''将预约成功和开始前的提醒定时发送给微信'''
    if students_id is None:
        students_id = list(appoint.students.values_list('Sid', flat=True))
    # write by cdf end2
    # modify by pht: 如果已经开始，非临时预约记录log
    if datetime.now() >= appoint.Astart:
        # add by lhw : 临时预约 #
        if appoint.Atype == Appoint.Type.TEMPORARY:
            set_appoint_wechat(
                appoint, MessageType.TEMPORARY.value,
                students_id=students_id, id=f'{appoint.Aid}_new_wechat')
        else:
            logger.warning(f'预约{appoint.Aid}尝试发送给微信时已经开始，且并非临时预约')
            return False
    elif datetime.now() <= appoint.Astart - timedelta(minutes=15):
        # 距离预约开始还有15分钟以上，提醒有新预约&定时任务
        if notify_create:  # 只有在非长线预约中才添加这个job
            set_appoint_wechat(
                appoint, MessageType.NEW.value,
                students_id=students_id, id=f'{appoint.Aid}_new_wechat')
        set_appoint_wechat(
            appoint, MessageType.START.value,
            students_id=students_id, id=f'{appoint.Aid}_start_wechat',
            job_time=appoint.Astart - timedelta(minutes=15))
    else:
        # 距离预约开始还有不到15分钟，提醒有新预约并且马上开始
        set_appoint_wechat(
            appoint, MessageType.NEW_AND_START.value,
            students_id=students_id, id=f'{appoint.Aid}_new_wechat')
    return True


def set_longterm_wechat(appoint: Appoint, students_id=None, infos='', admin=False):
    '''长期预约的微信提醒，默认发给所有参与者'''
    set_appoint_wechat(appoint, MessageType.LONGTERM_CREATED.value, infos,
                       students_id=students_id, admin=admin,
                       id=f'{appoint.Aid}_longterm_created_wechat')


def set_longterm_reviewing_wechat(longterm_appoint: LongTermAppoint, auditor_ids=None):
    '''长期预约的审核老师通知提醒，发送给对应的审核老师'''
    if auditor_ids is None:
        auditor_ids = get_auditor_ids(longterm_appoint.applicant.Sid)
    if not auditor_ids:
        return
    infos = []
    if longterm_appoint.applicant != longterm_appoint.appoint.major_student:
        infos.append(f'申请者：{longterm_appoint.applicant.name}')
    set_appoint_wechat(longterm_appoint.appoint, MessageType.LONGTERM_REVIEWING.value, *infos,
                       students_id=auditor_ids,
                       url=f'/review?Lid={longterm_appoint.pk}',
                       id=f'{longterm_appoint.pk}_longterm_review_wechat')


def cancel_scheduler(appoint_or_aid: Appoint | int, record_miss: bool = False) -> bool:
    '''以结束定时任务标识预约是否终止，未终止时取消所有定时任务，返回是否删除'''
    if isinstance(appoint_or_aid, Appoint):
        aid = appoint_or_aid.Aid
    else:
        aid = appoint_or_aid
    try:
        scheduler.remove_job(f'{aid}_finish')
        try:
            scheduler.remove_job(f'{aid}_start')
        except:
            if record_miss:
                logger.warning(f"预约{aid}取消时未发现开始计时器")
        try:
            scheduler.remove_job(f'{aid}_start_wechat')
        except:
            if record_miss:
                logger.info(f"预约{aid}取消时未发现wechat计时器")
        return True
    except:
        if record_miss:
            logger.warning(f"预约{aid}取消时未发现计时器")
        return False


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

    # 检查是否为临时预约 add by lhw (2021.7.13)
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

        # --- modify by lhw: Astart 可能比datetime.now小 --- #
        #assert Astart > datetime.now(), 'Appoint time error'
        assert Afinish > datetime.now(), 'Appoint time error'
        # --- modify end: 2021.7.10 --- #
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
            conflict_appoints = utils.get_conflict_appoints(appoint, lock=True)
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
            set_start_wechat(appoint, students_id, notify_create=notify_create)

            get_user_logger(major_student).info(f"发起预约，预约号{appoint.Aid}")

    except Exception as e:
        major_display = major_student.__str__()
        logger.exception(f"学生{major_display}出现添加预约失败的问题: {e}")
        return _error('添加预约失败!请与管理员联系!')

    return _success(appoint.toJson())


def get_longterm_display(times: int, interval_week: int, type: str = 'adj'):
    if type == 'adj':
        if interval_week == 1:
            longterm_info = f'{times}周的'
        elif interval_week == 2:
            longterm_info = f'{times}次单/双周的'
        else:
            longterm_info = f'{times}次间隔{interval_week}周的'
    else:
        if interval_week == 1:
            longterm_info = '每周一次'
        elif interval_week == 2:
            longterm_info = '隔周一次'
        else:
            longterm_info = f'每{interval_week}周一次'
        longterm_info += f' 共{times}次'
    return longterm_info


def add_longterm_appoint(appoint: 'Appoint | int',
                         times: int,
                         interval: int = 1,
                         week_offset: int = None,
                         admin: bool = False):
    '''
    自动开启事务以检查预约是否冲突，以原预约为模板直接生成新预约，不检查预约时间是否合法
    appoint无效时可能出错，否则不出错

    :param appoint: 预约的模板，Appoint类型视为可修改，不应再使用，否则作为主键
    :type appoint: Appoint | int
    :param times: 长期预约次数
    :type times: int
    :param interval: 每次预约间的间隔周数, defaults to 1
    :type interval: int, optional
    :param week_offset: 首个预约距模板的周数，默认从模板后一次预约开始, defaults to None
    :type week_offset: int, optional
    :param admin: 以管理员权限创建，本参数暂被忽视, defaults to False
    :type admin: bool, optional
    :return: 首个冲突预约所在次数、以开始时间升序排列的冲突或生成的预约集合
    :rtype: (int, QuerySet[Appoint])  | (None, QuerySet[Appoint])
    '''
    with transaction.atomic():
        # 默认不包含传入预约当周
        if week_offset is None:
            week_offset = interval
        # 获取模板
        if not isinstance(appoint, Appoint):
            origin_pk = appoint
            appoint: Appoint = Appoint.objects.get(pk=origin_pk)
        else:
            origin_pk = appoint.pk

        # 检查冲突
        conflict_appoints = utils.get_conflict_appoints(
            appoint, times, interval, week_offset, lock=True)
        if conflict_appoints:
            first_conflict = conflict_appoints[0]
            first_time = ((first_conflict.Afinish - appoint.Astart
                           - timedelta(weeks=week_offset)
                           ) // timedelta(weeks=interval) + 1)
            return first_time, conflict_appoints

        # 没有冲突，开始创建长线预约
        students = appoint.students.all()
        new_appoints = []
        new_appoint = appoint
        new_appoint.add_time(timedelta(weeks=week_offset))
        for time in range(times):
            # 先获取复制对象的副本
            new_appoint.Astatus = Appoint.Status.APPOINTED
            new_appoint.Atype = Appoint.Type.LONGTERM
            # 删除主键会被视为新对象，save时向数据库添加对象并更新主键
            new_appoint.pk = None
            new_appoint.save()
            new_appoint.students.set(students)
            new_appoints.append(new_appoint.pk)
            new_appoint.add_time(timedelta(weeks=interval))

        # 获取长线预约集合，由于生成是按顺序的，默认排序也是按主键递增，无需重排
        new_appoints = Appoint.objects.filter(pk__in=new_appoints)
        # 至此，预约都已成功创建，可以放心设置定时任务了，但设置定时任务出错也需要回滚
        for new_appoint in new_appoints:
            set_scheduler(new_appoint)
            set_start_wechat(new_appoint, notify_create=False)

    # 长线化预约发起成功，准备消息提示即可
    longterm_info = get_longterm_display(times, interval)
    get_user_logger(appoint).info(f"发起{longterm_info}长线化预约, 原预约号为{origin_pk}")
    return None, new_appoints
