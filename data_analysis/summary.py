from django.db.models import *
from app.constants import *
from app.models import *
from Appointment.models import Appoint
from Appointment import GLOBAL_INFO
from datetime import *

SUMMARY_YEAR = 2021
SUMMARY_SEM_START = datetime(2021, 9, 1)
 
def generic_info():
    generic_info = {}
    generic_info.update(cal_all_org())
    generic_info.update(cal_all_course())
    return generic_info


def person_info(np: 'NaturalPerson|User'):
    if isinstance(np, User):
        np = NaturalPerson.objects.get_by_user(np)
    person_info = {}
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
    total_courseorg_num = Organization.objects.filter(otype__otype_name='书院课程').count()
    total_act = Activity.objects.exclude(status__in=[
            Activity.Status.REVIEWING,
            Activity.Status.CANCELED,
            Activity.Status.ABORT,
            Activity.Status.REJECT
        ]).filter(year=SUMMARY_YEAR)
    total_act_num = total_act.count()
    total_act_hour: timedelta = sum([(a.end-a.start) for a in total_act], timedelta(0))
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
    total_course_act_hour: timedelta = sum([(a.end-a.start) for a in course_act], timedelta(0))
    total_course_act_hour = round(total_course_act_hour.total_seconds() / 3600, 2)

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


#
__persons = None


def cal_sharp_appoint(np: NaturalPerson):
    appoints = Appoint.objects.filter(
        Astart__gte=SUMMARY_SEM_START, 
        Astart__lt=GLOBAL_INFO.semester_start, 
        major_student__Sid=np.person_id)
    sharp_appoints = appoints.exclude(Atype=Appoint.Type.TEMPORARY).filter(
        Astart__lte=F('Atime') + timedelta(minutes=5))
    sharp_appoint_num = sharp_appoints.count()
    if not sharp_appoint_num:
        return dict(sharp_appoint_num=sharp_appoint_num)
    sharp_appoint: Appoint = min(sharp_appoints, key=lambda x: x.Astart-x.Atime)
    sharp_appoint_day = sharp_appoint.Astart.strftime('%Y年%m月%d日')
    sharp_appoint_reason = sharp_appoint.Ausage
    sharp_appoint_min = sharp_appoint.Astart - sharp_appoint.Atime
    sharp_appoint_min = round((sharp_appoint_min.total_seconds() / 60) % 60)
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
        Astart__lt=GLOBAL_INFO.semester_start,
        major_student__Sid=np.person_id
    )
    total_time = appoints.aggregate(time=Sum(F('Afinish')-F('Astart')))['time'] or timedelta()
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
    activity_awards = []
    if act_num == 0:
        activity_awards.append('“潜水冠军”')
    if orgs.count() >= 2 or act_num >= 5:
        activity_awards.append('“社牛”')
    if pos.count() >= 5:
        activity_awards.append('“我全都要”')
    return dict(
        IScreate=IScreate, myclub_name=myclub_name,
        club_num=club_num, course_org_num=course_org_num, act_num=act_num,
        activity_award='，'.join(activity_awards)
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
    for course_type in list(Course.CourseType): # CourseType.values亦可
        t = course_me_past.filter(course__type=course_type)
        if not t:
            continue
        t = t.aggregate(Sum('total_hours'), Sum('attend_times'))
        pro.append([course_type.label, t['total_hours__sum'] or 0, t['attend_times__sum'] or 0])

    unclassified_hour = course_me_past.filter(course__isnull=True).aggregate(
        Sum('total_hours'))['total_hours__sum'] or 0
    course_hour = 0
    
    types = []
    for label, hour, _ in pro:
        types.append(label)
        course_hour += hour

    if unclassified_hour:
        types.append('其它')
        course_hour += unclassified_hour

    course_type = '/'.join(types) + f' {len(types)}'
    IsOneType, IsManyType = len(types) == 1, len(types) > 1

    if course_me_past:
        most_time: CourseRecord = max(course_me_past, key=lambda x: x.total_hours)
        most_num: CourseRecord = max(course_me_past, key=lambda x: x.attend_times)
        course_most_time_name, course_most_hour = most_time.get_course_name(), most_time.total_hours
        course_most_num_name, course_most_num = most_num.get_course_name(), most_num.attend_times
    else:
        course_most_time_name, course_most_hour = "无", 0
        course_most_num_name, course_most_num = "无", 0

    return dict(course_num=course_num, course_hour=course_hour, course_type=course_type,
        course_most_time_name=course_most_time_name, course_most_hour=course_most_hour,
        course_most_num_name=course_most_num_name, course_most_num=course_most_num,
        IsOneType=IsOneType, IsManyType=IsManyType
        )
