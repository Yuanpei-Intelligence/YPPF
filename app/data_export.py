from app.models import (CourseRecord, Feedback, NaturalPerson)

import pandas as pd
from typing import Callable
from datetime import datetime
from django.db.models import Q, Sum, CharField, IntegerField, Count

__all__ = ['course_data', 'feedback_data']


def course_data(year: IntegerField = None,
                semester: CharField = None,
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
    courses = pd.DataFrame(columns=('年级', '学号', '门数', '次数', '学时'))
    relate_filter_kws = {
        f'courserecord__{k}': v
        for k, v in filter_kws.items()
    }
    person_record = all_person.annotate(
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
                     **relate_filter_kws))).order_by('person_id__username')
    for person in person_record:
        courses.loc[len(courses.index)] = [
            person.stu_grade,   # 年级
            hash_func(str(person.person_id)) if hash_func is not None \
                               else person.person_id,    # 学号
            CourseRecord.objects.filter(**filter_kws,person=person).count(),  # 总门数
            person.record_times if include_invalid is False \
                else person.record_times + person.invalid_times,     # 次数
            person.record_hours if include_invalid is False \
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
    feedbacks = pd.DataFrame(columns=('年级', '学号', '提交反馈数', '已解决反馈数'))
    person_record = all_person.annotate(
        total_num=Count('feedback', filter=Q(**filter_kws)),
        solved_num=Count('feedback',
                         filter=Q(
                             feedback__solve_status=0,
                             **filter_kws))).order_by('person_id__username')
    for person in person_record:
        feedbacks.loc[len(feedbacks.index)]=[
            person.stu_grade,    # 年级
            hash_func(str(person.peron_id)) if hash_func is not None \
                               else person.person_id,    # 学号
            person.total_num,      # 总提交数
            person.solved_num      # 已解决提交数
            ]
    return feedbacks