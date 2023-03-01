from typing import Iterable
from datetime import datetime, timedelta

from Appointment.extern.constants import MessageType
from extern.wechat import send_wechat
from Appointment.models import Room, Participant, Appoint
from Appointment.utils.log import logger
from utils.http.utils import build_full_url


__all__ = [
    'MessageType',
    'send_wechat_message',
    'notify_appoint',
]


ShowOptions = tuple[bool, bool, bool, bool]

def get_display_info(
    message_type: MessageType | str,
    reason: str,
) -> tuple[str, ShowOptions, list[str]]:
    title = '地下室预约提醒'
    show_time_and_place = True  # 显示预约时间地点
    show_main_student = True    # 显示发起人
    show_appoint_info = True    # 显示预约人员信息，包括用途 人数
    show_announcement = False   # 显示提供给其他参与者的预约信息
    extra_info = []
    match message_type:
        case MessageType.ADMIN.value:
            title = '管理员通知'
            show_time_and_place = False
            show_appoint_info = False
            extra_info = ['内容：' + reason]
        case MessageType.NEW.value:
            title = '您有一条新的预约'
            show_announcement = True
        case MessageType.START.value:
            title = '您有一条预约即将在15分钟后开始'
            show_announcement = True
        case MessageType.NEW_AND_START.value:
            title = '您有一条新的预约并即将在15分钟内开始'
            show_announcement = True
        case MessageType.VIOLATED.value:
            title = '您有一条新增的违约记录'
            show_main_student = False
            show_appoint_info = False
            extra_info = ['原因：' + reason]
        case MessageType.CANCELED.value:
            title = '您有一条预约被取消'
        case MessageType.LONGTERM_CREATED.value:
            # 发起一条长线预约
            title = f'您有一条新的长期预约'
            show_announcement = True
            if reason:
                extra_info = ['详情：' + reason]
        case MessageType.LONGTERM_REVIEWING.value:
            # 发送给审核老师
            title = f'您有一条待处理的长期预约'
            extra_info = ['去审核']
        case MessageType.LONGTERM_APPROVED.value:
            title = f'您的长期预约已通过审核'
        case MessageType.LONGTERM_REJECTED.value:
            title = f'您的长期预约未通过审核'
        case MessageType.WAITING2CONFIRM.value:
            title = '您有一条预约已确认完成'
            show_main_student = False
        case MessageType.VIOLATED2JUDGED.value:
            title = '您有一条违约的预约申诉成功'
            show_main_student = False
        case MessageType.VIOLATE_BY_ADMIN.value:
            title = '您有一条预约被判定违约'
            show_main_student = False
            extra_info = [
                '常见违规原因包括：用途不实、盗用他人信息预约、将功能房用作其他用途等',
                '请尽快取消同类预约，避免再次扣分',
                '如有疑问请联系管理员或咨询反馈',
                ]
            if reason:
                extra_info = [reason] + extra_info
        case MessageType.NEED_AGREE.value:
            title = '您刷卡的房间需要签署协议'
            show_main_student = False
            show_appoint_info = False
            extra_info = ['点击本消息即可快捷跳转到用户协议页面']
        case MessageType.TEMPORARY.value:
            title = '您发起了一条临时预约'
        case MessageType.TEMPORARY_FAILED.value:
            title = '您发起的临时预约失败'
            show_main_student = False
            show_appoint_info = False
            extra_info = ['原因：' + reason]
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
    is_admin: bool | None = None,
):
    '''
    room: 将被调用str方法，所以可以不是实际的房间
    appointer: str, 人名 不是学号！
    '''
    title, show_options, extra_info = get_display_info(message_type, reason)
    show_time_and_place, show_main_student, show_appoint_info, show_announcement = show_options

    if is_admin is None:
        is_admin = MessageType.ADMIN.value in message_type
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
    is_admin: bool | None = None,
):
    '''
    stuid_list: Iter[sid] 学号列表，不是学生!
    start_time: datetime | Any, 后者调用str方法
    room: 将被调用str方法，所以可以不是实际的房间
    major_student: str, 人名 不是学号！
    '''
    title, message = _build_message(
        message_type, start_time, room, major_student, usage,
        announcement, num, reason, is_admin)
    url = _build_url(url)
    send_wechat(stuid_list, title, message,
                card=True, url=url, btntxt='预约详情', multithread=False)


def notify_appoint(
    appoint: Appoint, message_type: str, *extra_infos: str,
    students_id: list[str] | None = None,
    url: str | None = None,
    admin: bool | None = None,
    id: str | None = None,
    job_time: datetime | timedelta | None = None,
):
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
    from scheduler.scheduler import scheduler
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
