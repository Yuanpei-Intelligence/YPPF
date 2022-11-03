from django.db.models import *
from app.constants import *
from app.models import *
from Appointment.models import Appoint, CardCheckInfo, Room
from Appointment.utils.identity import get_participant
from Appointment import GLOBAL_INFO
from datetime import *
from collections import defaultdict, Counter

SUMMARY_YEAR = 2021
SUMMARY_SEM_START = datetime(2021, 9, 1)
SUMMARY_SEM_END: datetime = GLOBAL_INFO.semester_start


def remove_local_var(d: dict):
    keys = list(d.keys())
    for k in keys:
        if k.startswith('_'):
            d.pop(k)
        if k == 'np':
            d.pop(k)
    return d


def generic_info():
    generic_info = {}
    generic_info.update(cal_all_org())
    generic_info.update(cal_all_course())
    return generic_info


def person_info(np: 'NaturalPerson|User'):
    if isinstance(np, User):
        np = NaturalPerson.objects.get_by_user(np)
    person_info = dict(Sname=np.name)
    person_info.update(cal_study_room(np))
    person_info.update(cal_early_room(np))
    person_info.update(cal_late_room(np))
    person_info.update(cal_appoint(np))
    person_info.update(cal_appoint_kw(np))
    person_info.update(cal_co_appoint(np))
    person_info.update(cal_sharp_appoint(np))
    person_info.update(cal_appoint_sum(np))
    person_info.update(cal_act(np))
    person_info.update(cal_course(np))
    return person_info


def person_infos(min=0, max=10000, count=10000):
    npd = {}
    for np in NaturalPerson.objects.filter(
            person_id__id__gte=min, person_id__id__lte=max
    ).select_related('person_id'):
        npd[np.person_id.username] = person_info(np)
        count -= 1
        if count <= 0:
            break
    return npd


# 通用统计部分从此开始
__generics = None


def cal_all_org():
    total_club_num = ModifyOrganization.objects.filter(
        otype__otype_name='学生小组', status=ModifyOrganization.Status.CONFIRMED).count()
    total_courseorg_num = Organization.objects.filter(
        otype__otype_name='书院课程').count()
    total_act = Activity.objects.exclude(status__in=[
        Activity.Status.REVIEWING,
        Activity.Status.CANCELED,
        Activity.Status.ABORT,
        Activity.Status.REJECT
    ]).filter(year=SUMMARY_YEAR)
    total_act_num = total_act.count()
    total_act_hour: timedelta = sum(
        [(a.end-a.start) for a in total_act], timedelta(0))
    total_act_hour = round(total_act_hour.total_seconds() / 3600, 2)
    return dict(total_club_num=total_club_num, total_courseorg_num=total_courseorg_num,
                total_act_num=total_act_num, total_act_hour=total_act_hour
                )


def cal_all_course():
    total_course_num = Course.objects.exclude(status=Course.Status.ABORT).filter(
        year=SUMMARY_YEAR).count()
    course_act = Activity.objects.exclude(status__in=[
        Activity.Status.REVIEWING,
        Activity.Status.CANCELED,
        Activity.Status.ABORT,
        Activity.Status.REJECT
    ]).filter(
        year=SUMMARY_YEAR, category=Activity.ActivityCategory.COURSE)

    total_course_act_num = len(course_act)
    total_course_act_hour: timedelta = sum(
        [(a.end-a.start) for a in course_act], timedelta(0))
    total_course_act_hour = round(
        total_course_act_hour.total_seconds() / 3600, 2)

    persons = NaturalPerson.objects.annotate(cc=Count(
        'courseparticipant', filter=Q(
            courseparticipant__course__year=SUMMARY_YEAR,
            courseparticipant__status__in=[
                CourseParticipant.Status.SELECT,
                CourseParticipant.Status.SUCCESS],
        )))
    have_course_num = persons.filter(cc__gte=1).count()
    have_three_course_num = persons.filter(cc__gte=3).count()

    return dict(total_course_num=total_course_num,
                total_course_act_num=total_course_act_num, total_course_act_hour=total_course_act_hour,
                have_course_num=have_course_num, have_three_course_num=have_three_course_num
                )


__persons = None

def test_wrapper(func):
    def _(np):
        try:
            return func(np)
        except:
            return {}
    return _


def cal_sharp_appoint(np: NaturalPerson):
    appoints = Appoint.objects.filter(
        Astart__gte=SUMMARY_SEM_START,
        Astart__lt=SUMMARY_SEM_END,
        major_student__Sid=np.person_id)
    sharp_appoints = appoints.exclude(Atype=Appoint.Type.TEMPORARY).filter(
        Astart__lt=F('Atime') + timedelta(minutes=30))
    sharp_appoint_num = sharp_appoints.count()
    if not sharp_appoint_num:
        return dict(sharp_appoint_num=sharp_appoint_num)
    sharp_appoint: Appoint = min(
        sharp_appoints, key=lambda x: x.Astart-x.Atime)
    sharp_appoint_day = sharp_appoint.Astart.strftime('%Y年%m月%d日')
    sharp_appoint_reason = sharp_appoint.Ausage
    sharp_appoint_min = (sharp_appoint.Astart - sharp_appoint.Atime).total_seconds()
    if sharp_appoint_min < 60:
        sharp_appoint_min = f'{round(sharp_appoint_min)}秒'
    else:
        sharp_appoint_min = f'{round((sharp_appoint_min / 60) % 60)}分钟'
    sharp_appoint_room = str(sharp_appoint.Room)
    disobey_num = appoints.filter(Astatus=Appoint.Status.VIOLATED).count()
    return dict(
        sharp_appoint_num=sharp_appoint_num,
        sharp_appoint_day=sharp_appoint_day,
        sharp_appoint_reason=sharp_appoint_reason,
        sharp_appoint_min=sharp_appoint_min,
        sharp_appoint_room=sharp_appoint_room,
        disobey_num=disobey_num
    )


def cal_appoint_sum(np: NaturalPerson):
    appoints = Appoint.objects.not_canceled().filter(
        Astart__gte=SUMMARY_SEM_START,
        Astart__lt=SUMMARY_SEM_END,
        major_student__Sid=np.person_id
    )
    total_time = appoints.aggregate(
        time=Sum(F('Afinish')-F('Astart')))['time'] or timedelta()
    appoint_hour = round(total_time.total_seconds() / 3600, 1)
    appoint_num = appoints.count()

    return dict(
        appoint_hour=appoint_hour, appoint_num=appoint_num,
        # poem_word=??
    )


def cal_act(np: NaturalPerson):
    orgs = ModifyOrganization.objects.filter(
        pos=np.person_id, status=ModifyOrganization.Status.CONFIRMED)
    IScreate = bool(orgs)
    myclub_name = ''
    if IScreate:
        myclub_name = '，'.join(orgs.values_list('oname', flat=True))
    pos = Position.objects.activated(noncurrent=None).filter(
        person=np,
        year=SUMMARY_YEAR
    )
    club_num = pos.filter(org__otype__otype_name='学生小组').count()
    course_org_num = pos.filter(org__otype__otype_name='书院课程').count()
    act_num = Participant.objects.activated().filter(
        person_id=np,
        activity_id__year=SUMMARY_YEAR
    ).count()
    position_num = pos.count()
    return dict(
        IScreate=IScreate, myclub_name=myclub_name,
        club_num=club_num, course_org_num=course_org_num, act_num=act_num,
        position_num=position_num,
    )


def cal_course(np: NaturalPerson):
    # course_num = Course.objects.exclude(
    #     status=Course.Status.ABORT).filter(
    #         year=SUMMARY_YEAR,
    #         participant_set__person=np,
    #         participant_set__status__in=[
    #             CourseParticipant.Status.SELECT,
    #             CourseParticipant.Status.SUCCESS,
    #             CourseParticipant.Status.FAILED,
    #         ]).count()

    course_me_past = CourseRecord.objects.filter(
        person=np, invalid=False, year=SUMMARY_YEAR)

    course_num = course_me_past.count()

    pro = []
    # 计算每个类别的学时
    for course_type in list(Course.CourseType):  # CourseType.values亦可
        t = course_me_past.filter(course__type=course_type)
        if not t:
            continue
        t = t.aggregate(Sum('total_hours'), Sum('attend_times'), count=Count('*'))
        pro.append([course_type.label, t['total_hours__sum']
                   or 0, t['attend_times__sum'] or 0, t['count'] or 0])

    unclassified_hour = course_me_past.filter(course__isnull=True).aggregate(
        Sum('total_hours'))['total_hours__sum'] or 0
    course_hour = 0

    types = []
    max_type_info = '无', 0
    for label, hour, _, count in pro:
        if count > max_type_info[1]:
            max_type_info = label, count
        types.append(label)
        course_hour += hour

    if unclassified_hour:
        types.append('其它')
        course_hour += unclassified_hour

    course_type = '/'.join(types) + f' {len(types)}'
    type_count = len(types)

    if course_me_past:
        most_time: CourseRecord = max(
            course_me_past, key=lambda x: x.total_hours)
        most_num: CourseRecord = max(
            course_me_past, key=lambda x: x.attend_times)
        course_most_time_name, course_most_hour = most_time.get_course_name(), most_time.total_hours
        course_most_num_name, course_most_num = most_num.get_course_name(), most_num.attend_times
    else:
        course_most_time_name, course_most_hour = "无", 0
        course_most_num_name, course_most_num = "无", 0

    return dict(course_num=course_num, course_hour=course_hour, course_type=course_type,
                course_most_time_name=course_most_time_name, course_most_hour=course_most_hour,
                course_most_num_name=course_most_num_name, course_most_num=course_most_num,
                max_type_info=max_type_info, type_count=type_count
                )


def cal_study_room(np: NaturalPerson):

    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _study_room_record_filter = Q(Cardroom__Rtitle__contains='自习',
                                  Cardtime__gt=_start_time,
                                  Cardtime__lt=_end_time,
                                  Cardstudent=_par)

    _study_room_reords = CardCheckInfo.objects.filter(
        _study_room_record_filter)

    if not _study_room_reords.exists():
        return dict(study_room_num=0)
    study_room_num = _study_room_reords.aggregate(cnt=Count('*')).get('cnt', 0)
    study_room_day = _study_room_reords.values_list('Cardtime__date').annotate(
        cnt=Count('*')).aggregate(cnt=Count('*')).get('cnt', 0)
    _cnt_dict = defaultdict(int)
    for r, _, _ in _study_room_reords.values_list('Cardroom__Rid', 'Cardtime__date').annotate(cnt=Count('*')):
        _cnt_dict[r] += 1
    study_room_top, study_room_top_day = max(
        [(r, cnt) for r, cnt in _cnt_dict.items()], key=lambda x: x[1])
    return dict(study_room_num=study_room_num,
                study_room_day=study_room_day,
                study_room_top=study_room_top,
                study_room_top_day=study_room_top_day,
                )


def cal_early_room(np: NaturalPerson):

    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _record_filter = Q(Cardtime__gt=_start_time,
                       Cardtime__lt=_end_time,
                       Cardstudent=_par,
                       Cardtime__hour__lt=8,
                       Cardtime__hour__gte=6)
    _room_reords = CardCheckInfo.objects.filter(_record_filter)
    if not _room_reords.exists():
        return dict(early_day_num=0)
    early_day_num = _room_reords.values_list('Cardtime__date').annotate(
        cnt=Count('*')).aggregate(cnt=Count('*')).get('cnt', 0)
    if early_day_num:
        early_room, early_room_day, early_room_time = min(list(_room_reords.values_list(
            'Cardroom__Rid', 'Cardtime__date').annotate(time=Min('Cardtime__time'))), key=lambda x: x[2])
    return remove_local_var(locals())


def cal_late_room(np: NaturalPerson):

    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _record_filter = Q(Cardtime__gt=_start_time,
                       Cardtime__lt=_end_time,
                       Cardstudent=_par)
    _late_filter_night = Q(Cardtime__hour__gte=23)
    _late_filter_dawn = Q(Cardtime__hour__lt=5)
    _room_reords = CardCheckInfo.objects.filter(_record_filter)
    late_room_num = len(list(set(_room_reords.filter(
        _late_filter_night).values_list('Cardtime__date'))))
    if not late_room_num:
        return dict(late_room_num=0)
    _dawn_records = list(_room_reords.filter(_late_filter_dawn).values_list(
        'Cardroom', 'Cardtime__date', 'Cardtime__time'))
    if _dawn_records:
        _latest_record = max(_dawn_records, key=lambda x: x[2])
    else:
        _latest_record = max(_room_reords.filter(_late_filter_night).values_list(
            'Cardroom', 'Cardtime__date', 'Cardtime__time'), key=lambda x: x[2])
    late_room, late_room_date, late_room_time = _latest_record
    _late_room_ref_date = late_room_date
    if late_room_time.hour < 23:
        _late_room_ref_date = late_room_date - timedelta(days=1)
    late_room_people = len(list(set(CardCheckInfo.objects.filter(Cardtime__gt=_start_time,
                                                    Cardtime__lt=_end_time,
                                                    Cardtime__date=_late_room_ref_date,
                                                    Cardtime__hour__gte=22
                                            ).values_list('Cardstudent'))))
    return locals()


def cal_appoint(np: NaturalPerson):

    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _talk_rooms = Room.objects.talk_rooms().values_list('Rid')
    _func_rooms = Room.objects.function_rooms().values_list('Rid')
    _me_act_appoint = Appoint.objects.not_canceled().filter(
        students=_par, Astart__gt=_start_time, Astart__lt=_end_time)
    _me_act_talk_appoint = _me_act_appoint.filter(Room__in=_talk_rooms)
    if not _me_act_appoint.exists():
        return {}
    if not _me_act_talk_appoint.exists():
        discuss_appoint_num = 0
    else:
        discuss_appoint_num = _me_act_talk_appoint.aggregate(cnt=Count('*'))['cnt']

        discuss_appoint_hour = sum([(finish - start).seconds for start,
                                finish in _me_act_talk_appoint.values_list('Astart', 'Afinish')])//3600
        _my_talk_rooms = _me_act_talk_appoint.values_list('Room')
        discuss_appoint_long_room, discuss_appoint_long_hour = max([(r[0], _me_act_appoint.filter(Room=r).aggregate(
            tol=Sum(F('Afinish') - F('Astart')))['tol'].total_seconds()//3600) for r in _my_talk_rooms], key=lambda x: x[1])
    appiont_most_day, appoint_most_num = Counter(
        _me_act_appoint.values_list('Astart__date')).most_common(1)[0]
    appiont_most_day = appiont_most_day[0].strftime('%m月%d日')

    _me_act_func_appoint = _me_act_appoint.filter(Room__in=_func_rooms)
    if not _me_act_func_appoint.exists():
        func_appoint_num = func_appoint_hour = 0
    else:
        func_appoint_num = _me_act_func_appoint.aggregate(cnt=Count('*'))['cnt']
        func_appoint_hour = _me_act_func_appoint.aggregate(
            tol=Sum(F('Afinish') - F('Astart')))['tol'].total_seconds()//3600
        # django 的 groupby 真的烂
        # func_appoint_most = _me_act_func_appoint.values_list('Room').annotate(cnt=Count('*'))
        func_appoint_most, func_appoint_most_hour = Counter(
            _me_act_func_appoint.values_list('Room__Rtitle')).most_common(1)[0]
        func_appoint_most = func_appoint_most[0]
    return remove_local_var(locals())


def cal_appoint_kw(np: NaturalPerson):
    import jieba

    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _talk_rooms = Room.objects.talk_rooms().values_list('Rid')
    _func_rooms = Room.objects.function_rooms().values_list('Rid')
    _me_act_appoint = Appoint.objects.not_canceled().filter(
        students=_par, Astart__gt=_start_time, Astart__lt=_end_time).exclude(Atype=Appoint.Type.TEMPORARY)

    _key_words = []
    for _usage in _me_act_appoint.values_list('Ausage'):
        _key_words.extend(jieba.cut(_usage[0]))
    Skeywords = Counter(_key_words).most_common(3)
    return remove_local_var(locals())


def cal_co_appoint(np: NaturalPerson):
    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _me_act_appoint = Appoint.objects.not_canceled().filter(
        students=_par, Astart__gt=_start_time, Astart__lt=_end_time)
    _co_np_list = []
    for appoint in _me_act_appoint:
        for _co_np in appoint.students.all():
            if _co_np != _par:
                _co_np_list.append(_co_np)
    if not _co_np_list:
        return {}
    co_mate, co_appoint_num = Counter(_co_np_list).most_common(1)[0]
    _co_act_appoint = _me_act_appoint.filter(students=co_mate)
    co_appoint_hour = _co_act_appoint.aggregate(
        tol=Sum(F('Afinish') - F('Astart')))['tol'].total_seconds()//3600
    co_mate = co_mate.name
    co_title = ''
    if co_appoint_hour > 30:
        co_title = '最好的朋友'
    elif co_appoint_hour > 15:
        co_title = '形影不离'
    elif co_appoint_hour > 8:
        co_title = '结伴同行'
    elif co_appoint_hour > 3:
        co_title = '感谢相遇'

    import jieba
    _key_words = []
    for usage in _co_act_appoint.values_list('Ausage'):
        if usage[0] in ['临时预约', '[MASK]']:
            continue
        _key_words.extend(jieba.cut(usage[0]))
    co_keyword = Counter(_key_words).most_common(1)[0]

    return remove_local_var(locals())
