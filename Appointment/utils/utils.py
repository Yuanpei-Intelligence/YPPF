# store some funcitons

import requests as requests
import json
from Appointment import *
import threading
from Appointment.models import Participant, Room, Appoint, CardCheckInfo  # 数据库模型
from django.contrib.auth.models import User
from django.db import transaction  # 原子化更改数据库
from django.db.models import Q
from datetime import datetime, timedelta
from django.http import JsonResponse
import os
import time

'''
YWolfeee:
utils.py中保存了一些比较杂碎的带有信息量的数据，例如对应表等。
微信消息的发送、日志的写入也在本文件中，使用前可以看一下代码的说明。
所有和scheduler无关、和互联网交互无关的工具函数，可以在本文件中实现。
'''

ip_room_dict = {
    "152": "B104",
    "155": "B104",
    "132": "B106",
    "153": "B106",
    "131": "B107A",
    "135": "B107B",
    "134": "B108",
    "151": "B108",
    "146": "B111",
    "149": "B111",
    "141": "B112",
    "148": "B112",
    # "138": "B114", # 不准 自习室
    "139": "B114",
    "144": "B118",
    "145": "B118",
    "140": "B119",
    "147": "B119",
    "129": "B205",
    "102": "B206",
    "106": "B206",
    "105": "B207",
    "107": "B207",
    "110": "B208",
    "111": "B208",
    "103": "B209",
    "108": "B209",
    "121": "B214",
    "128": "B214", # 镜子 舞蹈室
    "119": "B215",
    "117": "B216",
    "124": "B216", # 镜子 跑步机房
    "122": "B217",
    "126": "B217",
    "113": "B218",
    "120": "B220",
    "130": "B220",
    "112": "B221",  # 琴房 看不到门口谱子位置
    "123": "B221",  # 琴房 看不到小提琴位
    "118": "B222",
    "125": "B222",
}

door_room_dict = {
    "2020092016162884": "B104",
    "2020092016370963": "B106A",
    "2020092016422704": "B106B",
    "2020092016464351": "B107A",
    "2020092016550340": "B108A",
    "2020092017010542": "B108B",
    "2020092017070505": "B107B",
    "2020092017084647": "B000",  # 值班室
    "2020092017233640": "B112A",
    "2020092017234462": "B112B",
    "2020092017235201": "B111",
    "2020092017393941": "B114A",
    "2020092017475922": "B114B",
    "2020092017481264": "B118",
    "2020092017482150": "B119",
    "2020092018023538": "B218",
    "2020092018030345": "B220",
    "2020092018031303": "B221",
    "2020092018032470": "B222",
    "2020092018182960": "B214A",
    "2020092018184631": "B214B",
    "2020092018185928": "B216",
    "2020092018201454": "B217",
    "2020092018400410": "B209",
    "2020092018521223": "B205",
    "2020092018522586": "B206A",
    "2020092018523750": "B206B",
    "2020092018525770": "B208",
}

# 给定摄像头ip后三位，返回摄像头对应的Rid


def iptoroom(ip):
    return ip_room_dict[ip]


# 给定房间门牌号id，返回对应的Rid
def doortoroom(door):
    return door_room_dict[door]

############ modified by wxy ############


# 给企业微信发送消息
# update 0309:原来是返回状态码和错误信息，现在在这个函数中直接做错误处理，如果处理不了就写日志，不返回什么了
# update 0812:返回体信息发生了改变，以后只有errCode是权威的了，这里向下兼容了以前的版本
#             同时跳转链接也不再默认，需要手动提供，也进行了更新


send_message = requests.session()


def send_wechat_message(
    stuid_list,
    start_time,
    room,
    message_type,
    major_student,
    usage,
    announcement,
    num,
    reason='',
    url=None,
    is_admin=None,
):
    '''
    stuid_list: Iter[sid] 学号列表，不是学生!
    start_time: datetime | Any, 后者调用str方法
    room: 将被调用str方法，所以可以不是实际的房间
    major_student: str, 人名 不是学号！
    '''
    # --- modify by pht: 适当简化了代码 --- #

    try:start_time = start_time.strftime("%Y-%m-%d %H:%M")
    except:start_time = str(start_time)
    room = str(room)

    # 之后会呈现的信息只由以下的标题和两个列表拼接而成
    title = '地下室预约提醒'
    if is_admin is None:
        is_admin = 'admin' in message_type  # 决定标题呈现方式
    appoint_info = []
    show_time_and_place = True  # 显示预约时间地点
    show_main_student = True    # 显示发起人
    show_appoint_info = True    # 显示预约人员信息，包括用途 人数
    show_announcement = False   # 显示提供给其他参与者的预约信息
    extra_info = []

    if message_type == 'admin':
        title = '管理员通知'
        show_time_and_place = False
        show_appoint_info = False
        extra_info = ['内容：' + reason]
    elif message_type == 'new':
        title = '您有一条新的预约'
        show_announcement = True
    elif message_type == 'start':
        title = '您有一条预约即将在15分钟后开始'
        show_announcement = True
    elif message_type == 'new&start':
        title = '您有一条新的预约并即将在15分钟内开始'
        show_announcement = True
    elif message_type == 'violated':
        title = '您有一条新增的违约记录'  # 原因
        show_main_student = False
        show_appoint_info = False
        extra_info = ['原因：' + reason]  # '当前信用分：'+str(credit)
    elif message_type == 'cancel':
        title = '您有一条预约被取消'
    elif message_type.startswith('longterm'):    # 发起一条长线预约
        title = f'您有一条预约被长线化'
        show_announcement = True
        extra_info = ['详情：' + reason]
    elif message_type == 'confirm_admin_w2c':    # WAITING to CONFIRMED
        title = '您有一条预约已确认完成'
        show_main_student = False
    elif message_type == 'confirm_admin_v2j':    # VIOLATED to JUDGED
        title = '您有一条违约的预约申诉成功'
        show_main_student = False
    elif message_type == 'violate_admin':    # VIOLATED
        title = '您有一条预约被判定违约'
        show_main_student = False
        extra_info = [
            '常见违规原因包括：用途不实、盗用他人信息预约、将功能房用作其他用途等',
            '请尽快取消同类预约，避免再次扣分',
            '如有疑问请联系管理员或咨询反馈',
            ]
        if reason:
            extra_info = [reason] + extra_info
    elif message_type == 'need_agree':  # 需要签署协议
        title = '您刷卡的房间需要签署协议'
        show_main_student = False
        show_appoint_info = False
        extra_info = ['点击本消息即可快捷跳转到用户协议页面']
    elif message_type == 'temp_appointment':  # 临时预约
        title = '您发起了一条临时预约'
    elif message_type == 'temp_appointment_fail':  # 临时预约失败
        title = '您发起的临时预约失败'
        show_main_student = False
        show_appoint_info = False
        extra_info = ['原因：' + reason]
    else:
        # todo: 记得测试一下!为什么之前出问题的log就找不到呢TAT
        operation_writer(SYSTEM_LOG,
                        f'{start_time} {room} {message_type} ' + "出错，原因：unknown message_type", "utils.send_wechat_message",
                         "Problem")
        return
    
    try:
        if is_admin:
            title = f'【管理员操作】\n{title}<title>'
        else:
            title = title + '\n'

        if show_time_and_place:    # 目前所有信息都显示时间地点
            appoint_info += [f'时间：{start_time}', f'地点：{room}']
        
        if show_main_student:
            appoint_info += [f'发起者：{major_student}']

        if show_appoint_info:
            appoint_info += ['用途：' + usage, f'人数：{num}']
        
        if show_announcement and announcement:
            appoint_info += ['预约通知：' + announcement]
    
        message = title + '\n'.join(appoint_info + extra_info)

    except Exception as e:
        operation_writer(SYSTEM_LOG,
                         f"尝试整合信息时出错，原因：{e}", "utils.send_wechat_message",
                         "Problem")
    # --- modify end(2021.9.1) --- #

    secret = hash_wechat_coder.encode(message)
    url = url if url is not None else '/admin-index.html'
    if url.startswith('/'):
        url = GLOBAL_INFO.this_url.rstrip('/') + '/' + url.lstrip('/')
    post_data = {
        'touser': stuid_list,
        'toall': True,
        'content': message,
        'secret': secret,
        'card': True,
        'url': url,
        'btntxt': '预约详情',
    }
    response = send_message.post(
        GLOBAL_INFO.wechat_url, data=json.dumps(post_data))
    # for _ in range(0, 3):  # 重发3次
    for _ in range(0, 1):  # 不要重发，短时间重试没用，失败名单在内部重试--pht
        if _:
            time.sleep(1)   # 改成最后一次不休眠--pht
        if response.status_code != 200:
            # 正常连接永远返回200状态码
            # 只有能正常连接的时候才解析json数据，否则可能报错--pht
            operation_writer(SYSTEM_LOG,
                             f'{start_time} {room} {message_type} '+
                             f"向微信发消息失败，原因：状态码{response.status_code}异常",
                             "utils.send_wechat_message",
                             "Problem")
            continue
        response = response.json()
        if response['status'] == 200:
            operation_writer(SYSTEM_LOG,
                             f'{start_time} {room} {message_type} '+
                             "向微信发消息成功", "utils.send_wechat_message",
                             "OK")
            return
        # else check the reason, send wechat message again

        # 现在errMsg不再靠谱，改用errCode判断--pht
        code = response['data'].get('errCode')
        has_code = code is not None
        retry_enabled = (
                (200 <= code and code < 400 or str(code)[0] == '2') if 
                has_code else
                ('部分' in response['data']['errMsg'])  # 部分或全部发送失败/部分发送失败
            )
        # 别重发了
        retry_enabled = False

        if retry_enabled:
            if has_code and code != 206:
                operation_writer(SYSTEM_LOG,
                                f'{start_time} {room} {message_type} '+
                                f"企业微信返回了异常的错误码：{code}",
                                "utils.send_wechat_message",
                                "Problem")
                continue    # 目前仅206代表部分失败，可以重发，不应该出现200或其他
            stuid_list = [i[0] for i in response['data']['detail']]
            post_data = {
                'touser': stuid_list,
                'toall': True,
                'content': message,
                'secret': secret,
                'card': True,
                'url': url,
                'btntxt': '预约详情',
            }
            response = send_message.post(
                GLOBAL_INFO.wechat_url, data=json.dumps(post_data)) # 这里为啥是''
        else:
            # 之前的判断冗余，返回值只需判断是否有重发价值，错误信息照搬errMsg即可
            # 一般只可能是参数不规范(412)，企业微信出现问题会有应用不可见(404)
            err_msg = response['data']['errMsg']
            if has_code:
                err_msg = f'{code} ' + err_msg
            operation_writer(SYSTEM_LOG,
                             f'{start_time} {room} {message_type} '+
                             f"向微信发消息失败，原因：{err_msg}",
                             "utils.send_wechat_message",
                             "Problem")
            return
    # 重发都失败了
    operation_writer(SYSTEM_LOG,
                    f'{start_time} {room} {message_type} '+
                     "向微信发消息失败，原因：多次发送失败. 发起者为: " +
                     str(major_student), "utils.send_wechat_message",
                     "Problem")
    return
    # return  1, response['data']['errMsg']


# 线程锁，用于对数据库扣分操作时的排他性
lock = threading.RLock()
# 信用分扣除体系
real_credit_point = True  # 如果为false 那么不把扣除信用分纳入范畴


def set_appoint_reason(input_appoint, reason):
    '''预约的过程中检查迟到，先记录原因，并且进入到进行中状态，不一定扣分'''
    try:
        operation_succeed = False
        with transaction.atomic():
            appoints = Appoint.objects.select_for_update().filter(Aid=input_appoint.Aid)
            if len(appoints) != 1:
                raise AssertionError
            for appoint in appoints:
                if appoint.Astatus == Appoint.Status.APPOINTED:
                    appoint.Astatus = Appoint.Status.PROCESSING # 避免重复调用本函数
                appoint.Areason = reason
                appoint.save()
                operation_succeed = True
                
                # TODO: major_sid
                major_sid = str(appoint.major_student.Sid_id)
                aid = str(appoint.Aid)
                areason = str(appoint.get_Areason_display())
        if operation_succeed:
            operation_writer(major_sid, f"预约{aid}出现违约:{areason}",
                            f"utils.set_appoint_reason{os.getpid()}", "OK")
        return True, ""
    except Exception as e:
        return False, "in utils.set_appoint_reason: " + str(e)


def appoint_violate(input_appoint, reason):  # 将一个aid设为违约 并根据real_credit_point设置
    try:
        #lock.acquire()
        operation_succeed = False
        with transaction.atomic():
            appoints = Appoint.objects.select_related(
                'major_student').select_for_update().filter(Aid=input_appoint.Aid)
            if len(appoints) != 1:
                raise AssertionError
            for appoint in appoints:  # 按照假设，这里的访问应该是原子的，所以第二个程序到这里会卡主
                really_deduct = False

                if real_credit_point and appoint.Astatus != Appoint.Status.VIOLATED:  # 不出现负分；如果已经是violated了就不重复扣分了
                    if appoint.major_student.credit > 0:  # 这个时候需要扣分
                        appoint.major_student.credit -= 1
                        really_deduct = True
                    appoint.Astatus = Appoint.Status.VIOLATED
                    appoint.Areason = reason
                    appoint.save()
                    appoint.major_student.save()
                    operation_succeed = True

                    # TODO: major_sid
                    major_sid = str(appoint.major_student.Sid_id)
                    astart = appoint.Astart
                    aroom = str(appoint.Room)
                    major_name = str(appoint.major_student.name)
                    usage = str(appoint.Ausage)
                    announce = str(appoint.Aannouncement)
                    number = str(appoint.Ayp_num+appoint.Anon_yp_num)
                    status = str(appoint.get_status())
                    aid = str(appoint.Aid)
                    areason = str(appoint.get_Areason_display())
                    credit = str(appoint.major_student.credit)

        if operation_succeed:  # 本任务执行成功
            send_wechat_message([major_sid],
                                astart,
                                aroom,
                                "violated",
                                major_name,
                                usage,
                                announce,
                                number,
                                status,
                                #appoint.major_student.credit,
                                )  # totest: only main_student
            operation_writer(major_sid, f"预约{aid}出现违约:{areason}" +
                             f";扣除信用分:{really_deduct}" +
                             f";剩余信用分:{credit}",
                             f"utils.appoint_violate{os.getpid()}", "OK")  # str(os.getpid()),str(threading.current_thread().name()))
            #lock.release()
        return True, ""
    except Exception as e:
        return False, "in utils.appoint_violate: " + str(e)


# 文件操作体系
log_root = "logstore"
if not os.path.exists(log_root):
    os.mkdir(log_root)
log_root_path = os.path.join(os.getcwd(), log_root)
log_user = "user_detail"
if not os.path.exists(os.path.join(log_root_path, log_user)):
    os.mkdir(os.path.join(log_root_path, log_user))
log_user_path = os.path.join(log_root_path, log_user)

# 每周定时删除预约的程序，用于减少系统内的预约数量


def write_before_delete(appoint_list):
    date = str(datetime.now().date())

    write_path = os.path.join(log_root_path, date+".log")
    log = open(write_path, mode="a")  # open file

    period_start = (datetime.now()-timedelta(days=7)).date()
    log.write(str(period_start) + "~" + str(date) + "\n")
    for appoint in appoint_list:
        if appoint.Astatus != Appoint.Status.CANCELED:  # not delete
            log.write(str(appoint.toJson()).encode(
                "gbk", 'ignore').decode("gbk", "ignore"))
            log.write("\n")

    log.write("end of file\n")
    log.close()


# 通用日志写入程序 写入时间(datetime.now()),操作主体(Sid),操作说明(Str),写入函数(Str)
# 参数说明：第一为Sid也是文件名，第二位消息，第三位来源的函数名（类别）
def operation_writer(user, message, source, status_code="OK")-> None:
    lock.acquire()
    try:
        if isinstance(user, User):
            user = user.username
        timestamp = str(datetime.now())
        source = str(source).ljust(30)
        status = status_code.ljust(10)
        message = f"{timestamp} {source}{status}: {message}\n"

        with open(os.path.join(log_user_path, f"{str(user)}.log"), mode="a") as journal:
            journal.write(message)

        if status_code == "Error" and GLOBAL_INFO.debug_stuids:
            send_wechat_message(
                stuid_list=GLOBAL_INFO.debug_stuids,
                start_time=datetime.now(),
                room='地下室后台',
                message_type="admin",
                major_student="地下室系统",
                usage="发生Error错误",
                announcement="",
                num=1,
                reason=message,
                # credit=appoint.major_student.credit,
            )
    except Exception as e:
        # 最好是发送邮件通知存在问题
        # 待补充
        print(e)

    lock.release()


def cardcheckinfo_writer(Participant, Room, real_status, should_status, message=None):
    CardCheckInfo.objects.create(Cardroom=Room, Cardstudent=Participant,
                                 CardStatus=real_status, ShouldOpenStatus=should_status, Message=message)


def check_temp_appoint(room):
    return '研讨' in room.Rtitle


def get_conflict_appoints(appoint, times=1, interval=1, no_cross_day=False, lock=False):
    '''获取以时间排序的冲突预约，可以加锁，但不负责开启事务'''
    # 获取该房间的所有有效预约
    activate_appoints = Appoint.objects.not_canceled().filter(Room=appoint.Room)
    if lock:
        activate_appoints = activate_appoints.select_for_update()

    # 空的Q对象进行与和或运算的结果都是另一个操作数
    conditions = Q()
    if no_cross_day:
        conditions &= Q(
            # 开始比当前的结束时间早，结束比当前的开始时间晚
            Astart__time__lt=appoint.Afinish.time(),
            Afinish__time__gt=appoint.Astart.time(),
        )
        date_range = [
            appoint.Astart.date() + timedelta(days=7 * week)
            for week in range(0, times * interval, interval)
            ]
        conditions &= Q(
            Astart__date__in=date_range,
            Afinish__date__in=date_range,
        )
    else:
        for week in range(0, times * interval, interval):
            conditions |= Q(
                # 开始比当前的结束时间早
                Astart__lt=appoint.Afinish + timedelta(days=7 * week),
                # 结束比当前的开始时间晚
                Afinish__gt=appoint.Astart + timedelta(days=7 * week),
            )
    conflict_appoints = activate_appoints.filter(conditions)
    return conflict_appoints.order_by('Astart', 'Afinish')
