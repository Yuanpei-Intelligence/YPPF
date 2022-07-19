from app.models import (CourseRecord, Feedback, NaturalPerson)

import pandas as pd
from typing import Callable
from datetime import datetime
from django.db.models import F, Q, Sum, Prefetch

__all__ = ['course_data', 'feedback_data']


def course_data(start_time: datetime = None,
                end_time: datetime = None,
                hash_func: Callable = None,
                include_invalid: bool = False) -> pd.DataFrame:
    """
    获取书院课程的所有数据，返回一个时间从start_time到end_time的DataFrame。
    预约信息包含：姓名、 门数、 次数、 学时。

    :param start_time: 记录的起始时间, defaults to None（对起始时间无限制）
    :type start_time: datetime, optional
    :param end_time: 记录的终止时间, defaults to None（对终止时间无限制）
    :type end_time: datetime, optional
    :param hash_func: 进行数据脱敏的hash函数, defaults to None（不进行数据脱敏）
    :type hash_func: Callable, optional
    :param include_invalid: 是否计入无效学时，默认为不计入
    :type include_invalid: bool, optional
    :return: 记录书院课程数据的DataFrame
    :rtype: pd.DataFrame
    """
    all_person = NaturalPerson.objects.activated().filter(
        identity=NaturalPerson.Identity.STUDENT).order_by(
            'person__person_id__username')
    filter_kws = {}
    if start_time is not None:
        filter_kws.update(Astart__gte=start_time)
    if end_time is not None:
        filter_kws.update(Astart__lte=end_time)
    courses = pd.DataFrame(columns=('姓名', '门数', '次数', '学时'))
    for person in all_person:
        relate_filter_kws = {
            f'courserecord__{k}': v
            for k, v in filter_kws.items()
        }
        record_num = CourseRecord.objects.count()
        record_times = Sum(
            'courserecord__attend_times',
            filter(courserecord__invalid=False,
                   courserecord__person=person,
                   **relate_filter_kws))
        invalid_times = Sum(
            'courserecord__attend_times',
            filter(courserecord__invalid=True,
                   courserecord__person=person,
                   **relate_filter_kws))
        record_hours = Sum(
            'courserecord__total_hours',
            filter(courserecord__invalid=False,
                   courserecord__person=person,
                   **relate_filter_kws))
        invalid_hours = Sum(
            'courserecord__total_hours',
            filter(courserecord__invalid=True,
                   courserecord__person=person,
                   **relate_filter_kws))
        courses.loc[len(courses.index)] = [
            hash_func(str(person.peron_id.name)) if hash_func is not None \
                               else person.name,    # 姓名
            record_num,  # 总门数
            record_times if include_invalid is False \
                else record_times + invalid_times,     # 次数
            record_hours if include_invalid is False \
                else record_hours + invalid_hours     # 学时
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
            'person__person_id__username')
    filter_kws = {}
    if start_time is not None:
        filter_kws.update(feedback_time__gte=start_time)
    if end_time is not None:
        filter_kws.update(feedback_time__lte=end_time)
    feedbacks = pd.DataFrame(columns=('姓名', '提交反馈数', '已解决反馈数'))
    for person in all_person:
        records = Feedback.objects.filter(
            person=person,
            **filter_kws,
        )
        total_num = records.objects.count()
        solved_num = records.objects.filter(
            Feedback__SolveStatus=Feedback.SolveStatus.SOLVED).count()
        feedbacks.loc[len(feedbacks.index)]=[
            hash_func(str(person.peron_id.name)) if hash_func is not None \
                               else person.name,    # 姓名
            total_num,      # 总提交数
            solved_num      # 已解决提交数
            ]
    return feedbacks