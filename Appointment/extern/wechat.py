from typing import Iterable
from datetime import datetime, timedelta

from Appointment.extern.constants import MessageType
from extern.wechat import send_wechat
from Appointment.models import Room, Participant, Appoint, LongTermAppoint
from Appointment.utils.log import logger
from utils.http.utils import build_full_url


__all__ = [
    'MessageType',
    'notify_appoint',
]


ShowOptions = tuple[bool, bool, bool, bool]

def get_display_info(
    message_type: MessageType,
    reason: str,
) -> tuple[str, ShowOptions, list[str]]:
    title = '地下室预约提醒'
    show_time_and_place = True  # 显示预约时间地点
    show_main_student = True    # 显示发起人
    show_appoint_info = True    # 显示预约人员信息，包括用途 人数
    show_announcement = False   # 显示提供给其他参与者的预约信息
    extra_info = []
    match message_type:
        case MessageType.NEW:
            title = '您有一条新的预约'
            show_announcement = True
        case MessageType.REMIND:
            title = '您有一条预约即将在15分钟内开始'
            show_announcement = True
        case MessageType.NEW_INCOMING:
            title = '您有一条新的预约并即将在15分钟内开始'
            show_announcement = True
        case MessageType.VIOLATED:
            title = '您有一条新增的违约记录'
            show_main_student = False
            show_appoint_info = False
            extra_info = ['原因：' + reason]
        case MessageType.CANCELED:
            title = '您有一条预约被取消'
        case MessageType.LONGTERM_CREATED:
            # 发起一条长线预约
            title = f'您有一条新的长期预约'
            show_announcement = True
            if reason:
                extra_info = ['详情：' + reason]
        case MessageType.LONGTERM_REVIEWING:
            # 发送给审核老师
            title = f'您有一条待处理的长期预约'
            extra_info = ['去审核']
        case MessageType.LONGTERM_APPROVED:
            title = f'您的长期预约已通过审核'
        case MessageType.LONGTERM_REJECTED:
            title = f'您的长期预约未通过审核'
        case MessageType.PRE_CONFIRMED:
            title = '您有一条预约已确认完成'
            show_main_student = False
        case MessageType.APPEAL_APPROVED:
            title = '您有一条违约的预约申诉成功'
            show_main_student = False
        case MessageType.REVIEWD_VIOLATE:
            title = '您有一条预约被判定违约'
            show_main_student = False
            extra_info = [
                '常见违规原因包括：用途不实、盗用他人信息预约、将功能房用作其他用途等',
                '请尽快取消同类预约，避免再次扣分',
                '如有疑问请联系管理员或咨询反馈',
                ]
            if reason:
                extra_info = [reason] + extra_info
        case MessageType.TEMPORARY:
            title = '您发起了一条临时预约'
        case _:
            logger.error(f'未知消息类型：{message_type}')
            raise ValueError(f'未知消息类型：{message_type}')
    show_options = (show_time_and_place, show_main_student,
                    show_appoint_info, show_announcement,)
    return title, show_options, extra_info


def _build_message(
    message_type: str,
    time: datetime,
    room: Room | str,
    appointer: Participant | str,
    usage: str,
    announcement: str,
    total_count: int,
    reason: str = '',
    is_admin: bool = False,
):
    '''
    room: 将被调用str方法，所以可以不是实际的房间
    appointer: str, 人名 不是学号！
    '''
    title, show_options, extra_info = get_display_info(MessageType(message_type), reason)
    show_time_and_place, show_main_student, show_appoint_info, show_announcement = show_options

    if is_admin:
        title = f'【管理员操作】\n{title}'

    appoint_info = []
    if show_time_and_place:
        time_display = time.strftime("%Y-%m-%d %H:%M")
        if isinstance(room, Room):
            room = room.__str__()
        appoint_info += [f'时间：{time_display}', f'地点：{room}']
    if show_main_student:
        appoint_info += [f'发起者：{appointer}']
    if show_appoint_info:
        appoint_info += ['用途：' + usage, f'人数：{total_count}']
    if show_announcement and announcement:
        appoint_info += ['预约通知：' + announcement]

    return title, '\n'.join(appoint_info + extra_info)


def _build_url(url: str | None = None):
    if url is None:
        url = 'admin-index.html'
    return build_full_url(url, build_full_url('/underground/'))


def send_wechat_message(
    stuid_list: Iterable[str],
    start_time: datetime,
    room: Room | str,
    message_type: str,
    major_student: Participant | str,
    usage: str,
    announcement: str,
    num: int,
    reason: str = '',
    url: str | None = None,
    is_admin: bool = False,
):
    '''
    stuid_list: Iter[sid] 学号列表，不是学生!
    start_time: datetime | Any, 后者调用str方法
    room: 将被调用str方法，所以可以不是实际的房间
    major_student: str, 人名 不是学号！
    '''
    # TODO: 生产环境下，utils.utils需要包含这个函数，随后删除
    title, message = _build_message(
        message_type, start_time, room, major_student, usage,
        announcement, num, reason, is_admin)
    url = _build_url(url)
    send_wechat(stuid_list, title, message,
                card=True, url=url, btntxt='预约详情', multithread=False)


def _build_appoint_message(appoint: Appoint, message_type: MessageType,
                           *extra_infos: str, admin: bool):
    usage = '' if appoint.Ausage is None else appoint.Ausage
    announce = '' if appoint.Aannouncement is None else appoint.Aannouncement
    title, message = _build_message(message_type.value,
        appoint.Astart, appoint.Room, appoint.major_student.name, usage,
        announce, appoint.Anon_yp_num + appoint.Ayp_num, *extra_infos[:1],
        is_admin=admin,
    )
    return title, message


def notify_appoint(
    appoint: Appoint | LongTermAppoint, message_type: MessageType, *extra_infos: str,
    students_id: list[str] | None = None,
    url: str | None = None,
    admin: bool = False,
    id: str | None = None,
    job_time: datetime | timedelta | None = None,
):
    '''
    设置预约的微信提醒，默认发给所有参与者

    Args:
        appoint(Appoint | LongtermAppoint): 预约或长期预约
        message_type(MessageType): 消息类型
        extra_infos(str): 附加信息
        students_id(list[str], optional): 学号列表，默认为预约的所有参与者
        url(str, optional): 跳转链接，默认为账号主页
        admin(bool, optional): 是否为管理员操作，默认为否
        id(str, optional): 标识id，若为空则根据appoint参数主键生成任务id
        job_time(datetime | timedelta, optional): 任务执行时间或延迟，默认立即执行
    '''
    if isinstance(appoint, LongTermAppoint):
        _appoint = appoint.appoint
    else:
        _appoint = appoint
    if students_id is None:
        students_id = list(_appoint.students.values_list('Sid', flat=True))

    title, message = _build_appoint_message(
        _appoint, message_type, *extra_infos, admin=admin)
    if id is None:
        id = f'{appoint.pk}_{message_type.value}_notify'
    send_wechat(
        students_id, title, message,
        card=True, url=_build_url(url), btntxt='预约详情',
        task_id=id, run_time=job_time, multithread=True,
    )


def notify_user(student_id: str, title: str, *messages: str,
                place: str = '', time: datetime | None = None,
                url: str | None = None, btntxt: str = '详情'):
    '''微信通知单个用户'''
    if time is None:
        time = datetime.now()
    time_display = time.strftime("%Y-%m-%d %H:%M")
    appoint_info = [f'时间：{time_display}', f'地点：{place}']
    message = '\n'.join(tuple(appoint_info) + messages)
    send_wechat([student_id], title, message, card=True, url=_build_url(url), btntxt=btntxt)
