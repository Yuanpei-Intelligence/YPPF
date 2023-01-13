from datetime import datetime
from typing import Callable, Union, Type
import pandas as pd

from django.db import models
from django.db.models import (
    Q, Sum, CharField,
    Count, Aggregate, QuerySet
)

from app.models import *
from Appointment.models import Appoint


class BaseDump():

    @staticmethod
    def time_filter(data_model: Union[Type[models.Model], QuerySet],
                    start_time: datetime = None,
                    end_time: datetime = None,
                    start_time_field: str = 'time',
                    end_time_field: str = 'time',
                    year: int = None,
                    semester: Semester = None) -> QuerySet:
        """Time Filter 

        :param cls: Model or QuerySet
        :type cls: Union[models.Model, QuerySet]
        :return: filtered queryset
        :rtype: QuerySet
        """
        filter_kw = {}
        if start_time is not None:
            filter_kw[f'{start_time_field}__gt'] = start_time
        if end_time is not None:
            filter_kw[f'{end_time_field}__lt'] = end_time
        if year is not None:
            filter_kw['year'] = year
        if semester is not None:
            filter_kw['semester'] = semester
        if not isinstance(data_model, QuerySet):
            data_model = data_model.objects.all()
        return data_model.objects.filter(**filter_kw)

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        raise NotImplementedError


class PageTrackingDump(BaseDump):

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        user_page_data = pd.DataFrame(
            cls.time_filter(PageLog, options.get('start_time', None),
                            options.get('end_time', None))
                .values_list('user__username', 'type',
                            'url', 'time', 'platform'),
            columns=('用户', '类型', '页面', '时间', '平台'))
        if hash_func is not None:
            user_page_data['用户'].map(hash_func)
        return user_page_data


class ModuleTrackingDump(BaseDump):

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        user_module_data = pd.DataFrame(
            cls.time_filter(PageLog, options.get('start_time', None),
                            options.get('end_time', None))
                .values_list('user__username', 'type', 'module_name',
                            'url', 'time', 'platform'),
            columns=('用户', '类型', '模块', '页面', '时间', '平台'))
        if hash_func is not None:
            user_module_data['用户'].map(hash_func)
        return user_module_data


class AppointmentDump(BaseDump):

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        appoint_queryset = cls.time_filter(Appoint, options.get('start_time', None),
                                           options.get('end_time', None),
                                           start_time_field='Astart',
                                           end_time_field='Astart')
        appointments = pd.DataFrame(columns=('预约人', '参与者', '预约房间', 
                                             '开始时间', '结束时间', '预约用途'))
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


class OrgActivityDump(BaseDump):
    """小组活动参与度
    """

    @classmethod
    def dump(cls, **options) -> pd.DataFrame:
        org_name_field = 'organization_id__oname'
        return pd.DataFrame(
            cls.time_filter(Activity, options.get('start_time', None),
                            options.get('end_time', None), start_time_field='start',
                            end_time_field='start')
                .values_list(org_name_field, 'title', 'current_participants',
                             'start', 'end')
                .order_by(org_name_field),
            columns=('组织', '活动', '参与人数', '开始时间', '结束时间'))


class PersonPosDump(BaseDump):
    """个人小组参与情况
    """

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:

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
            cls.time_filter(Position, year=options.get('year', None), 
                            semester=options.get('semester', None))
                .values(sid_field)
                .annotate(count=Count('org'),
                          org_list=GroupConcat('org__oname', separator=','))
                .values_list(),
            columns=('用户', '参与组织个数', '参与组织'))
        if hash_func is not None:
            position_data['用户'].map(hash_func)
        return position_data


class PersonActivityDump(BaseDump):
    """个人活动参与记录，无聚合
    """

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        activity_queryset = cls.time_filter(Activity, year=options.get('year', None), 
                                            semester=options.get('semester', None))
        participants_data = pd.DataFrame(
            Participant.objects.filter(activity_id__in=activity_queryset)
                .values_list('person_id__person_id',
                             'activity_id__organization_id__oname',
                             'activity_id__title')
                .order_by('person_id__person_id'),
            columns=('用户', '组织', '活动'))
        if hash_func is not None:
            participants_data['用户'].map(hash_func)
        return participants_data


class PersonCourseDump(BaseDump):
    """个人书院课程参与记录
    包含：课程数量，有效次数，无效次数，有效时长，无效时长
    """

    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        course_data = pd.DataFrame(
            cls.time_filter(CourseRecord, year=options.get('year', None),
                            semester=options.get('semester', None))
                .values_list('person')
                .annotate(course_num=Count('id'),
                          record_times=Sum('attend_times', filter=Q(invalid=False)),
                          invalid_times=Sum('attend_times', filter=Q(invalid=True)),
                          record_hours=Sum('total_hours', filter=Q(invalid=False)),
                          invalid_hours=Sum('total_hours', filter=Q(invalid=True)))
                .values_list('person__person_id__username', 'course_num',
                             'record_times', 'invalid_times', 'record_hours',
                             'invalid_hours'),
            columns=('用户', '课程数量', '有效次数', '无效次数', '有效时长', '无效时长'))
        if hash_func is not None:
            course_data['用户'].map(hash_func)
        return course_data


class PersonFeedbackDump(BaseDump):
    """个人反馈数据记录
    包含：提交反馈数、解决反馈数。
    """
    @classmethod
    def dump(cls, hash_func: Callable = None, **options) -> pd.DataFrame:
        feedback_data = pd.DataFrame(
            cls.time_filter(Feedback, start_time=options.get('start_time', None),
                            end_time=options.get('end_time', None),
                            start_time_field='feedback_time',
                            end_time_field='feedback_time')
                .values_list('person')
                .annotate(total_num=Count('id'),
                          solved_num=Count('id', filter=Q(solve_status=Feedback.SolveStatus.SOLVED)))
                .values_list('person__person_id__username', 'total_num', 'solved_num'),
            columns=('用户', '提交反馈数', '已解决反馈数'))
        if hash_func is not None:
            feedback_data['用户'].map(hash_func)
        return feedback_data
