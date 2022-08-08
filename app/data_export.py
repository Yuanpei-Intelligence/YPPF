from typing import Callable
from datetime import datetime
import pandas as pd

from django.db.models import Q, Sum, CharField, IntegerField, Count, Aggregate

from app.models import (CourseRecord,
                        Feedback, 
                        NaturalPerson, 
                        Activity, 
                        Position)


__all__ = [
    'course_data',
    'feedback_data',
    'organization_data',
    'org_position_data',
]

def course_data(year: int = None,
                semester: str = None,
                hash_func: Callable = None,
                include_invalid: bool = False) -> pd.DataFrame:
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
    all_person = NaturalPerson.objects.activated().filter(
        identity=NaturalPerson.Identity.STUDENT).order_by(
            'person_id__username')
    filter_kws = {}
    if year is not None:
        filter_kws.update(year=year)
    if semester is not None:
        filter_kws.update(semester=semester)
    courses = pd.DataFrame(columns=('学号', '年级', '门数', '次数', '学时'))
    relate_filter_kws = {
        f'courserecord__{k}': v
        for k, v in filter_kws.items()
    }
    person_record = all_person.annotate(
        course_num=Count('courserecord', filter=Q(**relate_filter_kws)),
        record_times=Sum('courserecord__attend_times',
                         filter=Q(courserecord__invalid=False,
                                  **relate_filter_kws)),
        invalid_times=Sum('courserecord__attend_times',
                          filter=Q(courserecord__invalid=True,
                                   **relate_filter_kws)),
        record_hours=Sum('courserecord__total_hours',
                         filter=Q(courserecord__invalid=False,
                                  **relate_filter_kws)),
        invalid_hours=Sum(
            'courserecord__total_hours',
            filter=Q(courserecord__invalid=True,
                     **relate_filter_kws)))
    for i, person in enumerate(person_record):
        courses.loc[i] = [
            hash_func(str(person.person_id)) if hash_func is not None \
                                             else str(person.person_id),    # 学号
            person.stu_grade,   # 年级
            person.course_num,  #总门数
            person.record_times if include_invalid == False \
                                else person.record_times + person.invalid_times,     # 次数
            person.record_hours if include_invalid == False \
                                else person.record_hours + person.invalid_hours     # 学时
        ]
    return courses


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
    all_person = NaturalPerson.objects.activated().filter(
        identity=NaturalPerson.Identity.STUDENT).order_by(
            'person_id__username')
    filter_kws = {}
    if start_time is not None:
        filter_kws.update(feedback_time__gte=start_time)
    if end_time is not None:
        filter_kws.update(feedback_time__lte=end_time)
    feedbacks = pd.DataFrame(columns=('学号', '年级', '提交反馈数', '已解决反馈数'))
    person_record = all_person.annotate(
        total_num=Count('feedback', filter=Q(**filter_kws)),
        solved_num=Count('feedback',
                         filter=Q(
                             feedback__solve_status=Feedback.SolveStatus.SOLVED,
                             **filter_kws)))
    for i, person in enumerate(person_record):
        feedbacks.loc[i] = [
            hash_func(str(person.peron_id)) if hash_func is not None \
                                            else str(person.person_id),    # 学号
            person.stu_grade,      # 年级
            person.total_num,      # 总提交数
            person.solved_num      # 已解决提交数
        ]
    return feedbacks


def organization_data(start_time: datetime = None,
                      end_time: datetime = None,
                      hash_func: Callable = None) -> pd.DataFrame:
    """ 导出：组织数量，每个组织办的活动的数量及参与人数。
    
    :param start_time: 筛选的起始时间, defaults to None
    :type start_time: datetime, optional
    :param end_time: 筛选的终止时间, defaults to None
    :type end_time: datetime, optional
    :param hash_func: 脱敏函数, defaults to None
    :type hash_func: Callable, optional
    :return: 返回数据
    :rtype: pd.DataFrame
    """
    activity_queryset = Activity.objects.all()
    activity_frame = pd.DataFrame(columns=(
        "组织", "活动", "参与人数", "开始时间", "结束时间"
    ))
    # 按时间筛选
    if start_time:
        activity_queryset = activity_queryset.filter(start__gte=start_time)
    if end_time:
        activity_queryset = activity_queryset.filter(start__lte=end_time)
    org_name_field = 'organization_id__oname'
    activity_queryset = activity_queryset.values_list(
        org_name_field, 'title', 'current_participants', 'start', 'end'
        ).order_by(org_name_field)

    for acti in activity_queryset:
        activity_frame.loc[len(activity_frame.index)] = [
            acti[0], acti[1], acti[2],
            acti[3].strftime("%Y年%m月%d日 %H:%M"),    # 开始时间
            acti[4].strftime("%Y年%m月%d日 %H:%M"),   # 结束时间
        ]

    return activity_frame

def org_position_data(start_time: int = None,
                       end_time: int = None,
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
    person_frame = pd.DataFrame(columns=(
        "学号", "参与组织个数", "参与组织",
    ))
    position_queryset = Position.objects.all()
    if start_time:
        position_queryset = position_queryset.filter(in_year__gte=start_time)
    if end_time:
        position_queryset = position_queryset.filter(in_year__lte=end_time)

    sid_field = "person__person_id__username"  # 学号
    position_queryset = (
        position_queryset.values(sid_field)
        .annotate(
            count=Count('org'),
            orgalist=GroupConcat('org__oname', separator=",")
        ))

    for person in position_queryset:
        person_frame.loc[len(person_frame.index)] = [
            hash_func(person[sid_field]) if hash_func else person[sid_field],
            person['count'],
            person['orgalist']
        ]

    return person_frame
