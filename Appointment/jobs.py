# YWolfeee:
# 本py文件保留所有需要与scheduler交互的函数。
from datetime import datetime, timedelta

from django.db import transaction

from scheduler.periodic import periodical
from Appointment.config import appointment_config as CONFIG
from Appointment.models import Appoint
from Appointment.utils.utils import get_conflict_appoints
from Appointment.utils.log import write_before_delete, logger, get_user_logger
from Appointment.appoint.jobs import set_scheduler
from Appointment.extern.jobs import set_appoint_reminder


'''
YWolfeee:
本py文件中的所有函数，或者发起了一个scheduler任务，或者删除了一个scheduler任务。
这些函数大多对应预约的开始、结束，微信的定时发送等。
如果需要实现新的函数，建议先详细阅读本py中其他函数的实现方式。
'''

__all__ = [
    'get_longterm_display',
    'add_longterm_appoint',
]


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
            appoint = Appoint.objects.get(pk=origin_pk)
        else:
            origin_pk = appoint.pk

        # 检查冲突
        conflict_appoints = get_conflict_appoints(
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
            set_appoint_reminder(new_appoint)

    # 长线化预约发起成功，准备消息提示即可
    longterm_info = get_longterm_display(times, interval)
    get_user_logger(appoint).info(f"发起{longterm_info}长线化预约, 原预约号为{origin_pk}")
    return None, new_appoints
