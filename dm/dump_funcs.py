from datetime import datetime
from typing import Callable
import pandas as pd

from django.db import models
from django.db.models import (
    Q, Sum, CharField,
    Count, Aggregate, QuerySet
)

import utils.models.query as SQ
from generic.models import *
from record.models import *
from app.models import *
from Appointment.models import Appoint


class BaseDump():

    @staticmethod
    def time_filter(data_model: type[models.Model] | QuerySet,
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
        return data_model.filter(**filter_kw)

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
        org_name_field = SQ.f(Activity.organization_id, Organization.oname)
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
                    distinct=distinct,
                    ordering=' ORDER BY %s' % ordering if ordering is not None else '',
                    separator=' SEPARATOR "%s"' % separator,
                    output_field=CharField(),
                    **extra
                )

        position_data = pd.DataFrame(
            cls.time_filter(Position, year=options.get('year', None), 
                            semester=options.get('semester', None))
                .values(SQ.f(Position.person, NaturalPerson.person_id, User.username))
                .annotate(count=Count(SQ.f(Position.org)),
                          org_list=GroupConcat(
                              SQ.f(Position.org, Organization.oname), separator=','))
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
            Participation.objects.filter(SQ.mq(Participation.activity, IN=activity_queryset))
                .values_list(SQ.f(Participation.person, NaturalPerson.person_id),
                             SQ.f(Participation.activity, Activity.organization_id, Organization.oname),
                             SQ.f(Participation.activity, Activity.title))
                .order_by(SQ.f(Participation.person, NaturalPerson.person_id)),
            columns=('用户', '组织', '活动'))
        if hash_func is not None:
            participants_data['用户'].map(hash_func)
        return participants_data

