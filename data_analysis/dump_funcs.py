from typing import Any, Callable, List
from datetime import datetime
import pandas as pd

from django.db.models import (
    Q, Sum, CharField, IntegerField, Count, Aggregate
)

from app.models import *
from Appointment.models import Appoint
from data_analysis.utils import desensitize, time_filter


""" 埋点数据 """
def page_data(
        start_time: datetime = None,
        end_time: datetime = None,
        hash_func: Callable = None):
    page_data = time_filter(PageLog, start_time, end_time).values_list(
        'user__username', 'type', 'url', 'time', 'platform',
    )
    if hash_func is not None:
        page_data = desensitize(page_data, hash_func)
    return pd.DataFrame(page_data, columns=(
        '用户', '类型', '页面', '时间', '平台'
    ))


def module_data(
        start_time: datetime = None,
        end_time: datetime = None,
        hash_func: Callable = None):
    module_data = time_filter(ModuleLog, start_time, end_time).values_list(
        'user__username', 'type', 'module_name', 'url', 'time', 'platform',
    )
    if hash_func is not None:
        module_data = desensitize(module_data, hash_func)
    return pd.DataFrame(module_data, columns=(
        '用户', '类型', '模块', '页面', '时间', '平台'
    ))


""" 地下室数据 """
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


""" 小组数据 """
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
    activity_queryset = time_filter(
        Activity, start_time,
        end_time, start_time_field='start',
        end_time_field='start')
    org_name_field = 'organization_id__oname'
    return pd.DataFrame(
        activity_queryset.values_list(
            org_name_field, 'title',
            'current_participants', 'start', 'end'
        ).order_by(org_name_field),
        columns=('组织', '活动', '参与人数', '开始时间', '结束时间')
    )


def org_position_data(year: int = None,
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
    position_data = (
        time_filter(Position, year=year, semester=semester).values(sid_field)
        .annotate(
            count=Count('org'),
            orgalist=GroupConcat('org__oname', separator=',')
        )).values_list()
    if hash_func is not None:
        position_data = desensitize(position_data)
    return pd.DataFrame(position_data, columns=(
        '学号', '参与组织个数', '参与组织'
    ))


def participants_data(year: int = None,
                      semester: str = None,
                      hash_func: Callable = None) -> pd.DataFrame:
    activity_queryset = time_filter(Activity, year=year, semester=semester)
    return pd.DataFrame(
        Participant.objects.filter(activity_id__in=activity_queryset).values_list(
                'activity_id__title',
                'activity_id__organization_id__oname',
                'person_id__person_id'
            ).order_by(
                'activity_id__organization_id__oname',
                'activity_id__title'),
        columns=('活动', '组织', '参与人'))


""" 课程数据 """
def course_data(year: int = None,
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
    course_records = time_filter(CourseRecord, year=year, semester=semester)
    person_course_data = course_records.values_list('person').annotate(
        course_num=Count('id'),
        record_times=Sum('attend_times', filter=Q(invalid=False)),
        invalid_times=Sum('attend_times', filter=Q(invalid=True)),
        record_hours=Sum('total_hours', filter=Q(invalid=False)),
        invalid_hours=Sum('total_hours', filter=Q(invalid=True))
    ).values_list('person__person_id__username', 'course_num',
                  'record_times', 'invalid_times', 'record_hours', 'invalid_hours')
    if hash_func is not None:
        desensitize(person_course_data, hash_func)

    return pd.DataFrame(person_course_data, columns=(
        '用户', '课程数量', '有效次数', '无效次数', '有效时长', '无效时长'))


""" 反馈数据 """
def feedback_data(
    start_time: datetime = None,
    end_time: datetime = None,
    hash_func: Callable = None,
) -> pd.DataFrame:
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
    person_feedback_data = time_filter(Feedback, start_time=start_time, end_time=end_time,
                            start_time_field='feedback_time', end_time_field='feedback_time').values_list('person').annotate(
                                total_num=Count('id'),
                                solved_num=Count('id', filter=Q(solve_status=Feedback.SolveStatus.SOLVED))
                            ).values_list('person__person_id__username', 'total_num', 'solved_num')
    if hash_func is not None:
        desensitize(person_feedback_data, hash_func)
    return pd.DataFrame(person_feedback_data, columns=('用户', '提交反馈数', '已解决反馈数'))
