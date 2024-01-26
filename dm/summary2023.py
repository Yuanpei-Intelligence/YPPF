"""Generating summary data
TODO: Remove type errors
"""

from typing import Dict, Any
from datetime import *
from collections import defaultdict, Counter

from django.db.models import *
from django.db.models.functions import TruncDay

from utils.models.query import *
from app.config import *
from app.models import *
from app.YQPoint_utils import get_income_expenditure
from generic.models import User, YQPointRecord
from Appointment.models import Appoint, CardCheckInfo, Room
from Appointment.utils.identity import get_participant

# from Appointment.config import CONFIG

SUMMARY_YEAR1 = 2023
SUMMARY_SEMSTER1 = '秋'
SUMMARY_YEAR2 = 2022
SUMMARY_SEMSTER2 = '春'
SUMMARY_SEM_START = datetime(2023, 2, 1)
SUMMARY_SEM_END: datetime = datetime(2024, 1, 15)


def remove_local_var(d: Dict[str, Any]):
    keys = list(d.keys())
    for k in keys:
        if k.startswith('_'):
            d.pop(k)
        if k == 'np':
            d.pop(k)
        if k == 'jieba':
            d.pop(k)
    return d


def generic_info():
    generic_info = {}
    generic_info.update(cal_all_underground())
    generic_info.update(cal_all_org())
    generic_info.update(cal_all_course())
    return generic_info


def person_info(np: 'NaturalPerson|User'):
    if isinstance(np, User):
        np = NaturalPerson.objects.get_by_user(np)
    person_info = dict(Sname=np.name)
    # 个人的书院部分信息统计
    person_info.update(cal_login_num(np))
    person_info.update(cal_act(np))
    person_info.update(cal_course(np))
    person_info.update(cal_anual_yqpoint(np))
    person_info.update(cal_anual_academic(np))

    # 个人的地下室部分信息统计
    person_info.update(cal_study_room(np))
    person_info.update(cal_appoint(np))
    person_info.update(cal_sharp_appoint(np))
    person_info.update(cal_co_appoint(np))
    # person_info.update(cal_early_room(np))
    # person_info.update(cal_late_room(np))
    # person_info.update(cal_appoint_kw(np))
    # person_info.update(cal_appoint_sum(np))

    return person_info


def person_infos(min=0, max=10000, count=10000):
    npd = {}
    num = 0
    for np in NaturalPerson.objects.filter(
        mq(NaturalPerson.person_id, User.id, gte=min, lte=max)
    ).select_related(f(NaturalPerson.person_id)):
        npd[np.person_id.username] = person_info(np)
        count -= 1
        if count <= 0:
            break
        num += 1
        if num % 100 == 0:
            print(num)

    return npd


# 通用统计部分从此开始
__generics = None


def cal_all_underground():
    """
    - 地下室年度使用情况总览
        (1) 本年度地下室总刷卡记录
        (2) 本年度总研讨室预约次数、时长
        (3) 本年度总功能室预约次数、时长
        (4) 最受欢迎的研讨室和预约次数
        (5) 最受欢迎的功能房和预约次数
    """
    _room_reords = CardCheckInfo.objects.filter(
        Q(Cardtime__gt=SUMMARY_SEM_START, Cardtime__lt=SUMMARY_SEM_END,))
    _func_rooms = Room.objects.function_rooms().values_list('Rid')
    _talk_rooms = Room.objects.talk_rooms().values_list('Rid')

    # 总刷卡次数
    total_swipe_num = _room_reords.aggregate(cnt=Count('*')).get('cnt', 0)
    # 研讨室刷卡总次数
    total_talk_room_num = _room_reords.filter(
        Q(Cardroom__in=_talk_rooms)).aggregate(cnt=Count('*')).get('cnt', 0)
    # 研讨室预约总时长
    _act_appoint = Appoint.objects.not_canceled().filter(
        Astart__gt=SUMMARY_SEM_START, Astart__lt=SUMMARY_SEM_END)
    _act_talk_appoint = _act_appoint.filter(Room__in=_talk_rooms)
    total_discuss_appoint_hour = sum([(finish - start).seconds for start,
                                      finish in _act_talk_appoint.values_list('Astart', 'Afinish')])//3600
    # 最受欢迎的研讨室和预约次数
    total_talk_appoint_most_name, total_talk_appoint_most_num = Counter(
        _act_talk_appoint.values_list('Room__Rid')).most_common(1)[0]
    total_talk_appoint_most_name = total_talk_appoint_most_name[0]

    # 功能房刷卡总次数
    total_func_room_num = _room_reords.filter(
        Q(Cardroom__in=_func_rooms)).aggregate(cnt=Count('*')).get('cnt', 0)
    # 功能房预约总时长
    _act_func_appoint = _act_appoint.filter(Room__in=_func_rooms)
    total_func_appoint_hour = sum([(finish - start).seconds for start,
                                   finish in _act_func_appoint.values_list('Astart', 'Afinish')])//3600
    # 最受欢迎的功能房和预约次数
    total_func_appoint_most_name, total_func_appoint_most_num = Counter(
        _act_func_appoint.values_list('Room__Rid')).most_common(1)[0]
    total_func_appoint_most_name = total_func_appoint_most_name[0]

    return remove_local_var(locals())


def get_hottest_courses(year, semester):
    """
    根据年份和学期获取最热门的前三门课程
    """
    courses = Course.objects.filter(
        year=year, semester=semester).exclude(status=Course.Status.ABORT)

    # # 计算每门课程的预选人数
    course_with_preselect_count = courses.annotate(
        preselect_count=Count(
            'participant_set',
            filter=Q(participant_set__status__in=[
                CourseParticipant.Status.SELECT,
                CourseParticipant.Status.SUCCESS,
                CourseParticipant.Status.FAILED,
            ])
        )
    )
    # 计算预选人数与选课名额之比，使用ExpressionWrapper来确保结果为浮点数
    hottest_courses = course_with_preselect_count.annotate(
        hotness=ExpressionWrapper(
            F('preselect_count') / F('capacity'),
            output_field=FloatField()
        )
    ).order_by('-hotness')[:3]  # 按照hotness降序排列，并取前三门课程
    hottest_courses_list = []
    for course in hottest_courses:
        ele = {}
        ele[course.name] = course.hotness
        hottest_courses_list.append(ele)

    return hottest_courses_list


def cal_all_org():
    """
    - YPPF年度使用情况总览
        (1) 本年度所有小组、学生小组的总数
        (2) 本年度小组发起活动的总数量、总时长
    """
    # 所有小组的总数
    total_org_num = Organization.objects.activated().count()

    # 学生小组总数量
    total_club_num = ModifyOrganization.objects.filter(
        otype__otype_name='学生小组', status=ModifyOrganization.Status.CONFIRMED).count()

    # 活动总数量，注意这里是学年制
    total_act = Activity.objects.exclude(status__in=[
        Activity.Status.REVIEWING,
        Activity.Status.CANCELED,
        Activity.Status.ABORT,
        Activity.Status.REJECT
    ]).filter(Q(year=SUMMARY_YEAR1, semester=Semester.FALL) | Q(year=SUMMARY_YEAR2, semester=Semester.SPRING))
    total_act_num = total_act.count()
    # 总活动时长
    total_act_hour: timedelta = sum(
        [(a.end-a.start) for a in total_act], timedelta(0))
    total_act_hour = round(total_act_hour.total_seconds() / 3600, 2)

    return dict(total_org_num=total_org_num, total_club_num=total_club_num,
                total_act_num=total_act_num, total_act_hour=total_act_hour,
                )


def cal_all_course():
    """
    - YPPF年度使用情况总览
        (3) 书院本年度开课课程总数, 总课程活动数量
        (4) 本年度课程活动时长
        (5) 本年度参与一门课程的人数、参与三门课程的人数
        (6) 23年春季、秋季学期，最热门的三门书院课程（以预选人数和选课名额之比计算）
    """
    # 书院本年度开课总数
    total_course_num = Course.objects.exclude(status=Course.Status.ABORT).filter(
        Q(year=SUMMARY_YEAR1, semester=Semester.FALL) | Q(year=SUMMARY_YEAR2, semester=Semester.SPRING)).count()

    # 本年度课程活动
    course_act = Activity.objects.exclude(status__in=[
        Activity.Status.REVIEWING,
        Activity.Status.CANCELED,
        Activity.Status.ABORT,
        Activity.Status.REJECT
    ]).filter(
        Q(year=SUMMARY_YEAR1, semester=Semester.FALL) | Q(year=SUMMARY_YEAR2, semester=Semester.SPRING), category=Activity.ActivityCategory.COURSE)
    total_course_act_num = len(course_act)

    # 本年度课程活动时长
    total_course_act_hour: timedelta = sum(
        [(a.end-a.start) for a in course_act], timedelta(0))
    total_course_act_hour = round(
        total_course_act_hour.total_seconds() / 3600, 2)

    # 本年度参与一门课程的人数、参与三门课程的人数
    persons = NaturalPerson.objects.annotate(cc=Count(
        'courseparticipant', filter=Q(
            courseparticipant__course__year=SUMMARY_YEAR1,
            courseparticipant__course__semester=Semester.FALL,
            courseparticipant__status__in=[
                CourseParticipant.Status.SELECT,
                CourseParticipant.Status.SUCCESS],
        ) | Q(
            courseparticipant__course__year=SUMMARY_YEAR2,
            courseparticipant__course__semester=Semester.SPRING,
            courseparticipant__status__in=[
                CourseParticipant.Status.SELECT,
                CourseParticipant.Status.SUCCESS],
        )
    )
    )
    have_course_num = persons.filter(cc__gte=1).count()
    have_three_course_num = persons.filter(cc__gte=3).count()

    # 23年春季、秋季学期，最热门的三门书院课程（以预选人数和选课名额之比计算）
    hottest_courses_23_Fall = get_hottest_courses(
        year=SUMMARY_YEAR1, semester=Semester.FALL)
    hottest_courses_23_Spring = get_hottest_courses(
        year=SUMMARY_YEAR2, semester=Semester.SPRING)

    return dict(total_course_num=total_course_num,
                total_course_act_num=total_course_act_num, total_course_act_hour=total_course_act_hour,
                have_course_num=have_course_num, have_three_course_num=have_three_course_num,
                hottest_courses_23_Fall=hottest_courses_23_Fall,
                hottest_courses_23_Spring=hottest_courses_23_Spring
                )


# 个人统计部分从此开始
__persons = None


def cal_login_num(np: NaturalPerson):
    """
    - 系统登录介绍
        (0) 该用户的注册日期
        (1) 该用户本年度登陆系统次数
        (2) 该用户本年度最长连续登录系统天数
    """
    # 注册日期
    date_joined = np.get_user().date_joined
    # 该用户本年度登陆系统次数
    _user = np.get_user()
    _day_check_kws = {}
    _day_check_kws.update(time__date__gt=SUMMARY_SEM_START,
                          time__date__lt=SUMMARY_SEM_END)
    _signin_days = set(YQPointRecord.objects.filter(
        user=_user,
        source_type=YQPointRecord.SourceType.CHECK_IN,
        **_day_check_kws,
    ).order_by('time').values_list('time__date', flat=True).distinct())
    checkin_num = len(_signin_days)

    # 计算该用户最长连续登录系统天数
    _signin_days = sorted(_signin_days)
    max_consecutive_days = 0
    _current_streak = 0
    _previous_date = None

    for _current_date in _signin_days:
        if _previous_date is not None and _current_date == _previous_date + timedelta(days=1):
            # 如果当前日期和前一天相差一天，则增加连续天数
            _current_streak += 1
        else:
            # 否则，重置连续天数
            _current_streak = 1
        # 更新最大连续天数
        max_consecutive_days = max(max_consecutive_days, _current_streak)
        _previous_date = _current_date

    return {'date_joined': date_joined, 'checkin_num': checkin_num, 'max_consecutive_days': max_consecutive_days}


def cal_act(np: NaturalPerson):
    """
    - 小组板块
        (1) 该用户参与的学生小组与书院课程小组数量
        (2) 该用户创建或担任职务的小组名称、担任职务
        (3) 该用户参与的小组活动数
        (4) 该用户参与活动的出现频率最高的三个活动关键词、活动频率最高的时间段
    """
    import jieba.analyse
    from collections import defaultdict

    pos = Position.objects.activated(noncurrent=None).filter(
        Q(person=np, year=SUMMARY_YEAR1, semester__in=[Semester.FALL, Semester.ANNUAL]) | Q(
            person=np, year=SUMMARY_YEAR2, semester__in=[Semester.SPRING, Semester.ANNUAL]),
    )
    # 参与的学生小组的数量
    club_num = pos.filter(org__otype__otype_name='学生小组').count()
    # 参与的书院课程的数量
    course_org_num = pos.filter(org__otype__otype_name='书院课程').count()
    #
    participated_acts = Participation.objects.activated().filter(
        sq(Participation.person, np),
        (
            Q(activity__year=SUMMARY_YEAR1, activity__semester=Semester.FALL) |
            Q(activity__year=SUMMARY_YEAR2, activity__semester=Semester.SPRING)
        ))
    # 参与的活动的数量
    act_num = participated_acts.count()
    # 参与活动的关键词
    keyword_freq = defaultdict(int)
    activity_titles = participated_acts.values_list(
        'activity__title', flat=True)
    # 该用户参与活动的出现频率最高的三个活动关键词
    for text in activity_titles:
        for keyword in jieba.analyse.extract_tags(text):
            keyword_freq[keyword] += 1
    act_top_three_keywords = sorted(
        keyword_freq, key=keyword_freq.get, reverse=True)[:3]

    # 活动次数最高的时间段，按照每小时作为时间段。
    time_periods = Activity.objects.filter(id__in=participated_acts.values_list(
        'activity_id', flat=True)).values_list('start', 'end')
    if time_periods.exists():
        hour_frequencies = Counter()
        for start, end in time_periods:
            duration = int((end - start).total_seconds() / 3600)
            for hour in range(start.hour, start.hour + duration):
                hour_frequencies[hour % 24] += 1
        most_act_common_hour = hour_frequencies.most_common(1)[0][0]
    else:
        most_act_common_hour = None
    # 担任的职务的数量
    position_num = pos.count()
    # 担任负责人的小组名称
    admin_pos = pos.filter(is_admin=True)
    admin_org_names = [position.org.oname for position in admin_pos]

    # 该用户是否创建小组、创建的小组名称
    orgs = ModifyOrganization.objects.filter(
        pos=np.person_id, status=ModifyOrganization.Status.CONFIRMED)
    IScreate = bool(orgs)
    myclub_name = ''
    if IScreate:
        myclub_name = '，'.join(orgs.values_list('oname', flat=True))

    return dict(
        IScreate=IScreate, myclub_name=myclub_name,
        club_num=club_num, course_org_num=course_org_num, act_num=act_num,
        position_num=position_num, admin_org_names=admin_org_names,
        act_top_three_keywords=act_top_three_keywords, most_act_common_hour=most_act_common_hour
    )


def cal_course(np: NaturalPerson):
    """
    - 书院课程板块
        (1) 该用户选修的课程总数、总学时
        (2) 该用户选修的课程在五类课程中的哪几类
        (3) 该用户投入学时最长的课程及学时时长
        (4) 用户春季学期、秋季学期选课数量
        (5) 用户春季学期、秋季学期选中书院课数量
    """

    # 这里计算的实际参与的课程活动总数，即便学时可能无效，但是只要有学时，就算
    course_me_past = CourseRecord.objects.filter(person=np, total_hours__gt=0)
    course_num = course_me_past.count()

    # 计算每个类别学时的时候，只考虑有效学时
    course_me_past = course_me_past.filter(invalid=False)
    pro = []
    # 计算每个类别的学时
    for course_type in list(Course.CourseType):  # CourseType.values亦可
        t = course_me_past.filter(course__type=course_type)
        if not t:
            continue
        t = t.aggregate(Sum('total_hours'), Sum(
            'attend_times'), count=Count('*'))
        pro.append([course_type.label, t['total_hours__sum']
                   or 0, t['attend_times__sum'] or 0, t['count'] or 0])

    unclassified_hour = course_me_past.filter(course__isnull=True).aggregate(
        Sum('total_hours'))['total_hours__sum'] or 0

    # 个人选修课程的总学时，选修课程类别学时最多的是哪一类、多少学时
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

    # 该用户选修的课程在五类课程中的哪几类
    course_type = '/'.join(types) + f' {len(types)}'
    type_count = len(types)

    # 该用户投入学时最长的课程、学时时长、参与次数
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

    elect_course = Course.objects.exclude(
        status=Course.Status.ABORT).filter(
        participant_set__person=np,
        participant_set__status__in=[
            CourseParticipant.Status.SELECT,
            CourseParticipant.Status.SUCCESS,
            CourseParticipant.Status.FAILED,
        ])
    # 该用户23秋、23春课程选课数量(包含失败的情况)
    preelect_course_23fall = elect_course.filter(
        year=SUMMARY_YEAR1, semester=Semester.FALL,)
    preelect_course_23spring = elect_course.filter(
        year=SUMMARY_YEAR2, semester=Semester.SPRING,)
    preelect_course_23fall_num = preelect_course_23fall.count()
    preelect_course_23spring_num = preelect_course_23spring.count()

    # 该用户23秋、23春课程选上课数量
    elected_course_23fall_num = preelect_course_23fall.filter(
        participant_set__status__in=[
            CourseParticipant.Status.SELECT,
            CourseParticipant.Status.SUCCESS,
        ]).count()
    elected_course_23spring_num = preelect_course_23spring.filter(
        year=SUMMARY_YEAR2, semester=Semester.SPRING,
        participant_set__status__in=[
            CourseParticipant.Status.SELECT,
            CourseParticipant.Status.SUCCESS,
        ]).count()

    return dict(course_num=course_num,
                course_hour=course_hour, course_type=course_type,
                course_most_time_name=course_most_time_name, course_most_hour=course_most_hour,
                course_most_num_name=course_most_num_name, course_most_num=course_most_num,
                max_type_info=max_type_info, type_count=type_count,
                preelect_course_23fall_num=preelect_course_23fall_num,
                preelect_course_23spring_num=preelect_course_23spring_num,
                elected_course_23fall_num=elected_course_23fall_num,
                elected_course_23spring_num=elected_course_23spring_num,
                )


def cal_anual_yqpoint(np: NaturalPerson):
    """
    - 元气值板块
        (1) 获取元气值总值
        (2) 消耗元气值总值
        (3) 兑换奖品种类数量
        (4) 盲盒兑换次数、抽中次数
    """
    _user = np.get_user()
    # 获取元气值总值, 消耗元气值总值
    income, expenditure = get_income_expenditure(
        _user, SUMMARY_SEM_START, SUMMARY_SEM_END)

    _pool_records = PoolRecord.objects.filter(
        user=_user, time__gte=SUMMARY_SEM_START, time__lt=SUMMARY_SEM_END)
    _lucky_pool_records = _pool_records.filter(status__in=[
        PoolRecord.Status.UN_REDEEM,
        PoolRecord.Status.REDEEMED,
    ])
    _unique_prizes = _lucky_pool_records.values_list(
        'prize', flat=True).distinct()
    # 兑换奖品种类
    number_of_unique_prizes = len(_unique_prizes)
    # 盲盒兑换次数
    _mystery_boxes = _pool_records.filter(pool__type=Pool.Type.RANDOM)
    mystery_boxes_num = _mystery_boxes.count()
    # 盲盒抽中次数
    lukcy_mystery_boxes_num = _lucky_pool_records.filter(
        pool__type=Pool.Type.RANDOM).count()

    return remove_local_var(locals())


def cal_anual_academic(np: NaturalPerson):
    """
    - 学术地图板块
        (1) 学术地图标签关键词数量
        (2) 学术地图提问次数
    """
    _academic_tags = AcademicTagEntry.objects.activated().filter(person=np)
    academic_tags_num = _academic_tags.count()

    # # 获取并统计每种类型的标签数量
    # _tag_counts = _academic_tags.values('tag__atype').annotate(count=Count('tag')).order_by('tag__atype')

    # for _tag_count in _tag_counts:
    #     _atype = AcademicTag.Type(_tag_count['tag__atype']).label
    #     _count = _tag_count['count']

    # 学术地图提问次数
    academic_QA_num = AcademicQA.objects.filter(
        chat__questioner=np.get_user()).count()

    return remove_local_var(locals())


def cal_study_room(np: NaturalPerson):
    """
    - 自习室
        (1) 用户本年度自习室刷卡次数、天数、超越“%”的同学
        (2) 用户本年度最常去的自习室、次数
    """
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
    # 用户本年度自习室刷卡次数
    study_room_num = _study_room_reords.aggregate(cnt=Count('*')).get('cnt', 0)
    # 用户本年度自习室刷卡天数
    study_room_day = _study_room_reords.values_list('Cardtime__date').annotate(
        cnt=Count('*')).aggregate(cnt=Count('*')).get('cnt', 0)
    # 个人最常去的自习室，和对应的天数
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


def cal_anual_appoint(_me_appoint: QuerySet[Appoint], _room_type: str = None):
    """"
    根据不同的房间类型，获取以下内容：
        (1) 用户本年度{_room_type}总预约次数、总时长
        (2) 用户本年度最多使用的{_room_type}预约理由关键词
        (3) 用户本年度最多预约的{_room_type}、次数
        (5) {_room_type}预约时长最多的日期，当日预约时长，当天的预约关键词
    """
    import jieba.analyse
    if _room_type is None:
        # 所有类型房间
        _room_list = Room.objects.permitted().values_list('Rid')
    elif _room_type == 'Discuss':
        # 研讨室
        _room_list = Room.objects.talk_rooms().values_list('Rid')
    elif _room_type == 'Function':
        # 功能房
        _room_list = Room.objects.function_rooms().values_list('Rid')

    _me_act_appoints = _me_appoint.filter(Room__in=_room_list)
    if not _me_act_appoints.exists():
        appoint_num = appoint_hour = 0
    else:
        # 用户本年度{room_type}预约次数
        appoint_num = _me_act_appoints.aggregate(cnt=Count('*'))['cnt']
        # 用户本年度{room_type}预约时长
        appoint_hour = sum([(finish - start).seconds for start,
                            finish in _me_act_appoints.values_list('Astart', 'Afinish')])//3600
        # 用户本年度最长预约的{room_type}、时长
        # _my_rooms = set(_me_act_appoints.values_list('Room', flat=True))
        # appoint_long_room, appoint_long_hour = max([(r, _me_act_appoint.filter(Room=r).aggregate(
        #     tol=Sum(F('Afinish') - F('Astart')))['tol'].total_seconds()//3600) for r in _my_rooms], key=lambda x: x[1])

        # 用户本年度最多预约的{room_type}、次数
        appoint_most_room, appoint_most_room_num = Counter(
            _me_act_appoints.values_list('Room__Rtitle'), flat=True).most_common(1)[0]

        # 预约时长最多的日期，当日预约时长，当天的预约关键词
        # 计算每个预约的时长
        _discuss_duration_appointments = _me_act_appoints.annotate(
            duration=ExpressionWrapper(
                F('Afinish') - F('Astart'),
                output_field=DurationField()
            )
        )

        # 按天分组并计算总时长
        _daily_duration = _discuss_duration_appointments.annotate(
            day=TruncDay('Astart')
        ).values('day').annotate(
            total_duration=Sum('duration')
        ).order_by('-total_duration')

        # 获取时长最长的那一天
        _longest_day = _daily_duration.first() if _daily_duration else None

        if _longest_day:
            _hours, _remainder = divmod(
                _longest_day['total_duration'].seconds, 3600)
            _minutes = _remainder // 60
            if _minutes == 0:
                appoint_longest_duration = f"{_hours}小时"
            else:
                appoint_longest_duration = f"{_hours}小时{_minutes}分钟"
            appoint_longest_day = _longest_day['day']
            _purposes = _me_act_appoints.filter(
                Astart__date=appoint_longest_day).values_list('Ausage', flat=True)

            if len(_purposes) == 1:
                _keywords = jieba.analyse.extract_tags(_purposes[0], topK=1)
                appoint_longest_day_keyword = _keywords[0] if _keywords else None
            else:
                # 多个文本：提取频率最高的关键词
                _all_words = []
                for _text in _purposes:
                    _words = jieba.cut(_text)
                    _all_words.extend(_words)
                _most_common_words = Counter(_all_words).most_common(1)
                appoint_longest_day_keyword = _most_common_words[0][0] if _most_common_words else None
        else:
            appoint_longest_duration = None
            appoint_longest_day = None
            appoint_longest_day_keyword = None

    _room_dict = remove_local_var(locals())
    _prefix_room_dict = {f"{_room_type}_" +
                         _key: _value for _key, _value in _room_dict.items()}

    return _prefix_room_dict


def cal_appoint(np: NaturalPerson):
    """
    -研讨室
        (1) 用户本年度研讨室总预约次数、总时长
        (2) 用户本年度最多使用的研讨室预约理由关键词
        (3) 用户本年度最多预约的研讨室、次数
        (5) 研讨室预约时长最多的日期，当日预约时长，当天的预约关键词
    -功能房
        内容同研讨室
    """
    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    room_dict = {}
    if _par is None:
        return room_dict
    _me_act_appoint = Appoint.objects.not_canceled().filter(
        students=_par, Astart__gt=_start_time, Astart__lt=_end_time)
    if not _me_act_appoint.exists():
        return room_dict

    func_room_dict = cal_anual_appoint(_me_act_appoint, _room_type='Function')
    talk_room_dict = cal_anual_appoint(_me_act_appoint, _room_type='Discuss')
    room_dict.update(func_room_dict)
    room_dict.update(talk_room_dict)

    return room_dict


def cal_sharp_appoint(np: NaturalPerson):
    """
    - 极限预约 & 违约次数
        (1) 在预约时间前30分钟内预约次数
        (2) 预约最紧的一次的时长、日期、理由、房间号
        (3) 违约次数，总计扣分
    """
    appoints = Appoint.objects.filter(
        Astart__gte=SUMMARY_SEM_START,
        Astart__lt=SUMMARY_SEM_END,
        major_student__Sid=np.person_id)
    sharp_appoints = appoints.exclude(Atype=Appoint.Type.TEMPORARY).filter(
        Astart__lt=F('Atime') + timedelta(minutes=30))
    # 在预约时间前30分钟内预约次数
    sharp_appoint_num = sharp_appoints.count()
    if not sharp_appoint_num:
        return dict(sharp_appoint_num=sharp_appoint_num)
    # 预约最紧的一次的日期
    sharp_appoint: Appoint = min(
        sharp_appoints, key=lambda x: x.Astart-x.Atime)
    sharp_appoint_day = sharp_appoint.Astart.strftime('%Y年%m月%d日')
    sharp_appoint_reason = sharp_appoint.Ausage
    sharp_appoint_min = (sharp_appoint.Astart -
                         sharp_appoint.Atime).total_seconds()
    if sharp_appoint_min < 60:
        sharp_appoint_min = f'{round(sharp_appoint_min)}秒'
    else:
        sharp_appoint_min = f'{round((sharp_appoint_min / 60) % 60)}分钟'
    sharp_appoint_room = str(sharp_appoint.Room)

    # 违约次数
    disobey_num = appoints.filter(Astatus=Appoint.Status.VIOLATED).count()

    return dict(
        sharp_appoint_num=sharp_appoint_num,
        sharp_appoint_day=sharp_appoint_day,
        sharp_appoint_reason=sharp_appoint_reason,
        sharp_appoint_min=sharp_appoint_min,
        sharp_appoint_room=sharp_appoint_room,
        disobey_num=disobey_num
    )


def cal_co_appoint(np: NaturalPerson):
    """
    - 海内存知己,天涯若比邻
    (1) 该用户本年度一起预约最多的同学
    (2) 一起预约的次数、时长
    (3) 一起预约最多的理由
    (4) 获得称号
    """
    _start_time = SUMMARY_SEM_START
    _end_time = SUMMARY_SEM_END

    _user = np.get_user()
    _par = get_participant(_user)
    if _par is None:
        return {}

    _me_act_appoint = Appoint.objects.not_canceled().filter(
        students=_par, Astart__gt=_start_time, Astart__lt=_end_time)
    _co_np_list = []
    for _appoint in _me_act_appoint:
        for _co_np in _appoint.students.all():
            if _co_np != _par:
                _co_np_list.append(_co_np)
    if not _co_np_list:
        return {}
    # 该用户本年度一起预约最多的同学、次数
    co_mate, co_appoint_num = Counter(_co_np_list).most_common(1)[0]
    _co_act_appoint = _me_act_appoint.filter(students=co_mate)
    # 一起预约的时长
    co_appoint_hour = _co_act_appoint.aggregate(
        tol=Sum(F('Afinish') - F('Astart')))['tol'].total_seconds()//3600
    co_mate = co_mate.name
    # 获得称号
    co_title = ''
    if co_appoint_hour > 30:
        co_title = '莫逆之交'
    elif co_appoint_hour > 15:
        co_title = '形影不离'
    elif co_appoint_hour > 8:
        co_title = '结伴同行'
    elif co_appoint_hour > 3:
        co_title = '一拍即合'
    # 一起预约最多的理由
    import jieba
    _key_words = []
    for usage in _co_act_appoint.values_list('Ausage'):
        if usage[0] in ['临时预约', '[MASK]']:
            continue
        _key_words.extend(jieba.cut(usage[0]))
    co_keyword = Counter(_key_words).most_common(1)[0]

    return remove_local_var(locals())


# 本年度未用到以下部分
__useless = None


def cal_appoint_kw(np: NaturalPerson):
    """
    计算个人，年度预约关键词（最常出现的前三名）
    """
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


def cal_appoint_sum(np: NaturalPerson):
    """
    个人总预约时长、次数
    """
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


def cal_early_room(np: NaturalPerson):
    """
    计算个人 上午6-8点到达地下室的次数，每年度最早到地下室的时间
    """
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
    """
    计算个人 凌晨23-5点在地下室的次数，有多少人在同一时期陪同，哪间自习室陪你到最晚
    """
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
    return remove_local_var(locals())
