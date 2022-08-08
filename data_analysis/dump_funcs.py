from typing import Any, Callable, List
from datetime import datetime
import pandas as pd

from django.db.models import (
    Q, Sum, CharField, Count, Aggregate
)

from app.models import *
from Appointment.models import Appoint
from data_analysis.utils import time_filter


def page_data(start_time: datetime = None,
              end_time: datetime = None,
              hash_func: Callable = None) -> pd.DataFrame:
    user_page_data = pd.DataFrame(
        time_filter(PageLog, start_time, end_time)
            .values_list('user__username', 'type', 
                         'url', 'time', 'platform'),
        columns=('用户', '类型', '页面', '时间', '平台'))
    if hash_func is not None:
        user_page_data['用户'].map(hash_func)
    return user_page_data


def module_data(start_time: datetime = None,
                end_time: datetime = None,
                hash_func: Callable = None) -> pd.DataFrame:
    user_module_data = pd.DataFrame(
        time_filter(ModuleLog, start_time, end_time)
            .values_list('user__username', 'type', 'module_name',
                         'url', 'time', 'platform'),
        columns=('用户', '类型', '模块', '页面', '时间', '平台'))
    if hash_func is not None:
        user_module_data['用户'].map(hash_func)
    return user_module_data


def appointment_data(start_time: datetime = None,
                     end_time: datetime = None,
                     hash_func: Callable = None) -> pd.DataFrame:
    """
    获取地下室预约的所有数据，返回一个时间从start_time到end_time的DataFrame。
    预约信息包含：预约房间、预约人、参与者、开始时间、结束时间、预约用途。

    :param start_time: 预约记录的起始时间, defaults to None（对起始时间无限制）
    :type start_time: datetime, optional
    :param end_time: 预约记录的终止时间, defaults to None（对终止时间无限制）
    :type end_time: datetime, optional
    :param hash_func: 进行数据脱敏的hash函数, defaults to None（不进行数据脱敏）
    :type hash_func: Callable, optional
    :return: 记录地下室预约数据的DataFrame
    :rtype: pd.DataFrame
    """

    appoint_queryset = time_filter(
        Appoint, start_time, end_time, start_time_field='Astart', end_time_field='Astart')
    appointments = pd.DataFrame(columns=(
        '预约人', '参与者', '预约房间', '开始时间', '结束时间', '预约用途'
    ))
    for i, appoint in enumerate(appoint_queryset):
        appointments.loc[i] = [
            hash_func(str(appoint.major_student.Sid)) if hash_func is not None
            else appoint.major_student.name,                  # 预约人
            ','.join([hash_func(str(student.Sid)) if hash_func is not None \
                      else student.name for student in appoint.students.all()]),  # 参与者
            appoint.Room.Rid.strip('"') + ' ' + \
            appoint.Room.Rtitle.strip('"'),  # 预约房间
            appoint.Astart.strftime('%Y年%m月%d日 %H:%M'),    # 开始时间
            appoint.Afinish.strftime('%Y年%m月%d日 %H:%M'),   # 结束时间
            appoint.Ausage,                                  # 预约用途
        ]
    return appointments


def org_activity_data(start_time: datetime = None,
                      end_time: datetime = None,
                      hash_func: Callable = None) -> pd.DataFrame:
    """ 导出：小组数量，每个小组办的活动的数量及参与人数。

    :param start_time: 筛选的起始时间, defaults to None
    :type start_time: datetime, optional
    :param end_time: 筛选的终止时间, defaults to None
    :type end_time: datetime, optional
    :param hash_func: 脱敏函数, defaults to None
    :type hash_func: Callable, optional
    :return: 返回数据
    :rtype: pd.DataFrame
    """
    org_name_field = 'organization_id__oname'
    return pd.DataFrame(
        time_filter(Activity, start_time,
                    end_time, start_time_field='start',
                    end_time_field='start')
            .values_list(
                org_name_field, 'title',
                'current_participants', 'start', 'end')
            .order_by(org_name_field),
        columns=('组织', '活动', '参与人数', '开始时间', '结束时间'))


def person_position_data(year: int = None,
                         semester: str = None,
                         hash_func: Callable = None) -> pd.DataFrame:
    """导出：每个人参与了什么书院组织

    :param start_time: 筛选的起始学年, defaults to None
    :type start_time: int, optional
    :param end_time: 筛选的终止学年, defaults to None
    :type end_time: int, optional
    :param hash_func: 脱敏函数, defaults to None
    :type hash_func: Callable, optional
    :return: 返回数据
    :rtype: pd.DataFrame
    """
    class GroupConcat(Aggregate):  # 用于分类聚合查询
        function = 'GROUP_CONCAT'
        template = '%(function)s(%(distinct)s%(expressions)s%(ordering)s%(separator)s)'

        def __init__(self, expression, distinct=False, ordering=None, separator=',', **extra):
            super(GroupConcat, self).__init__(
                expression,
                distinct='DISTINCT ' if distinct else '',
                ordering=' ORDER BY %s' % ordering if ordering is not None else '',
                separator=' SEPARATOR "%s"' % separator,
                output_field=CharField(),
                **extra
            )

    sid_field = 'person__person_id__username'  # 学号
    position_data = pd.DataFrame(
        time_filter(Position, year=year, semester=semester)
            .values(sid_field)
            .annotate(
                count=Count('org'),
                org_list=GroupConcat('org__oname', separator=','))
            .values_list(),
        columns=('用户', '参与组织个数', '参与组织'))
    if hash_func is not None:
        position_data['用户'].map(hash_func)
    return position_data


def person_activity_data(year: int = None,
                         semester: str = None,
                         hash_func: Callable = None) -> pd.DataFrame:
    activity_queryset = time_filter(Activity, year=year, semester=semester)
    participants_data = pd.DataFrame(
        Participant.objects.filter(activity_id__in=activity_queryset)
            .values_list(
                'person_id__person_id',
                'activity_id__organization_id__oname',
                'activity_id__title')
            .order_by('person_id__person_id'),
        columns=('用户', '组织', '活动'))
    if hash_func is not None:
        participants_data['用户'].map(hash_func)
    return participants_data


def person_course_data(year: int = None,
                       semester: str = None,
                       hash_func: Callable = None) -> pd.DataFrame:
    """
    获取书院课程的所有数据，返回一个指定学期与年份的DataFrame。
    预约信息包含：姓名、 门数、 次数、 学时。

    :param year: 记录的年份, defaults to None（对年份无限制）
    :type year: IntergerField, optional
    :param semester: 记录的学期, defaults to None（对学期无限制）
    :type semester: CharField, optional
    :param hash_func: 进行数据脱敏的hash函数, defaults to None（不进行数据脱敏）
    :type hash_func: Callable, optional
    :param include_invalid: 是否计入无效学时，默认为不计入
    :type include_invalid: bool, optional
    :return: 记录书院课程数据的DataFrame
    :rtype: pd.DataFrame
    """
    course_data = pd.DataFrame(
        time_filter(CourseRecord, year=year, semester=semester)
            .values_list('person')
            .annotate(
                course_num=Count('id'),
                record_times=Sum('attend_times', filter=Q(invalid=False)),
                invalid_times=Sum('attend_times', filter=Q(invalid=True)),
                record_hours=Sum('total_hours', filter=Q(invalid=False)),
                invalid_hours=Sum('total_hours', filter=Q(invalid=True)))
            .values_list('person__person_id__username', 'course_num',
                  'record_times', 'invalid_times', 'record_hours', 'invalid_hours'),
        columns=('用户', '课程数量', '有效次数', '无效次数', '有效时长', '无效时长'))
    if hash_func is not None:
        course_data['用户'].map(hash_func)
    return course_data


def person_feedback_data(start_time: datetime = None,
                         end_time: datetime = None,
                         hash_func: Callable = None) -> pd.DataFrame:
    """
    获取反馈的所有数据，返回一个时间从start_time到end_time的DataFrame。
    反馈信息包含：提交反馈数、解决反馈数。

    :param start_time: 记录的起始时间, defaults to None（对起始时间无限制）
    :type start_time: datetime, optional
    :param end_time: 记录的终止时间, defaults to None（对终止时间无限制）
    :type end_time: datetime, optional
    :param hash_func: 进行数据脱敏的hash函数, defaults to None（不进行数据脱敏）
    :type hash_func: Callable, optional
    :return: 记录反馈数据的DataFrame
    :rtype: pd.DataFrame
    """
    feedback_data = pd.DataFrame(
        time_filter(Feedback, start_time=start_time, end_time=end_time,
                    start_time_field='feedback_time', end_time_field='feedback_time')
            .values_list('person')
            .annotate(
                total_num=Count('id'),
                solved_num=Count('id', filter=Q(solve_status=Feedback.SolveStatus.SOLVED)))
            .values_list('person__person_id__username', 'total_num', 'solved_num'),
        columns=('用户', '提交反馈数', '已解决反馈数'))
    if hash_func is not None:
        feedback_data['用户'].map(hash_func)
    return feedback_data
