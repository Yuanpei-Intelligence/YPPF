"""
Generate fake records. Only used in dev & test.
"""

from datetime import date

from generic.models import User
from app.models import *
from semester.models import Semester, SemesterType
from boot import config

USER_NAME = "1"
USER_NAME_2 = "2"
TEACHER_NAME = "10"
TEACHER_NAME_2 = "11"

ORGANIZATION_USER_NAME = ['zz00001', 'zz00002', 'zz00000']
ORGANIZATION_ONAME = ['绘画班', '舞蹈班', 'Official']


# TODO: Change Settings
assert config.DEBUG, 'Should not import fake_records in production env.'


def delete_all():
    User.objects.all().delete()
    OrganizationType.objects.all().delete()
    OrganizationTag.objects.all().delete()


def create_superuser():
    try:
        User.objects.create_superuser(username='admin', password='admin',
                                      email='admin@notexist.com')
    except:
        pass


def create_np():
    # TODO: Modify it
    sid = username = USER_NAME
    password = username
    name = "1号学生"
    gender = NaturalPerson.Gender.MALE
    stu_major = "元培计划（待定）"
    stu_grade = "2020"
    stu_class = 5
    email = sid + "@stu.pku.edu.cn"
    visit_times = 100
    tel = None
    biography = '我是1号学生'
    identity = NaturalPerson.Identity.STUDENT

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_newuser = False
    user.utype = User.Type.PERSON
    user.save()
    if created:
        stu = NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=sid,
            name=name,
            gender=gender,
            stu_major=stu_major,
            stu_grade=stu_grade,
            stu_class=stu_class,
            email=email,
            telephone=tel,
            visit_times=visit_times,
            biography=biography,
            identity=identity,
        )
        stu.save()

    sid = username = USER_NAME_2
    password = username
    name = "2号学生"
    gender = NaturalPerson.Gender.FEMALE
    stu_major = "元培计划（待定）"
    stu_grade = "2020"
    stu_class = 5
    email = sid + "@stu.pku.edu.cn"
    visit_times = 100
    tel = None
    biography = '我是2号学生'
    identity = NaturalPerson.Identity.STUDENT

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_newuser = False
    user.utype = User.Type.PERSON
    user.save()
    if created:
        stu = NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=sid,
            name=name,
            gender=gender,
            stu_major=stu_major,
            stu_grade=stu_grade,
            stu_class=stu_class,
            email=email,
            telephone=tel,
            visit_times=visit_times,
            biography=biography,
            identity=identity,
        )
        stu.save()

    sid = username = TEACHER_NAME
    password = username
    name = "1号老师"
    gender = NaturalPerson.Gender.MALE
    email = sid + "@pku.edu.cn"
    visit_times = 100
    tel = None
    biography = '我是1号老师'
    identity = NaturalPerson.Identity.TEACHER

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_newuser = False
    user.utype = User.Type.PERSON
    user.save()
    if created:
        tea = NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=sid,
            name=name,
            gender=gender,
            email=email,
            telephone=tel,
            visit_times=visit_times,
            biography=biography,
            identity=identity,
        )
        tea.save()

    sid = username = TEACHER_NAME_2
    password = username
    name = "2号老师"
    gender = NaturalPerson.Gender.MALE
    email = sid + "@pku.edu.cn"
    visit_times = 100
    tel = None
    biography = '我是2号老师'
    identity = NaturalPerson.Identity.TEACHER

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_newuser = False
    user.utype = User.Type.PERSON
    user.save()
    if created:
        tea = NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=sid,
            name=name,
            gender=gender,
            email=email,
            telephone=tel,
            visit_times=visit_times,
            biography=biography,
            identity=identity,
        )
        tea.save()


def create_org_type():
    otype_id = 1
    otype_name = '学生小组'

    user = User.objects.get(username=USER_NAME)
    incharge = NaturalPerson.objects.get_by_user(user)

    job_name_list = ['部长', '副部长', '部员']

    org_type = OrganizationType.objects.create(
        otype_id=otype_id,
        otype_name=otype_name,
        incharge=incharge,
        job_name_list=job_name_list,
    )
    org_type.save()


def create_org_tag():
    name = '兴趣'
    color = OrganizationTag.ColorChoice.red
    org_tag = OrganizationTag.objects.create(
        name=name,
        color=color,
    )
    org_tag.save()

    name_2 = '住宿生活'
    color_2 = OrganizationTag.ColorChoice.blue
    org_tag_2 = OrganizationTag.objects.create(
        name=name_2,
        color=color_2,
    )
    org_tag_2.save()


def create_org():

    for uname, oname in zip(ORGANIZATION_USER_NAME, ORGANIZATION_ONAME):
        user, created = User.objects.get_or_create(username=uname)
        user.utype = User.Type.ORG
        user.is_newuser = False
        user.set_password(uname)
        otype = OrganizationType.objects.get(otype_id=1)
        tags = OrganizationTag.objects.get(name='兴趣')
        user.save()

        if created:
            org = Organization.objects.create(
                organization_id=user,
                oname=oname,
                otype=otype,
            )
            org.tags.set([tags])
            org.save()


def create_position():
    # stu 1 is admin of hhb
    user = User.objects.get(username=USER_NAME)
    person = NaturalPerson.objects.get_by_user(user)

    org_user = User.objects.get(username=ORGANIZATION_USER_NAME[0])
    org = Organization.objects.get_by_user(org_user)
    pos = 0
    is_admin = 1

    Position.objects.create(
        person=person,
        org=org,
        pos=pos,
        is_admin=is_admin,
    )

    # stu 1 is one of wdb
    user = User.objects.get(username=USER_NAME)
    person = NaturalPerson.objects.get_by_user(user)

    org_user = User.objects.get(username=ORGANIZATION_USER_NAME[1])
    org = Organization.objects.get_by_user(org_user)
    pos = 1
    is_admin = 0

    Position.objects.create(
        person=person,
        org=org,
        pos=pos,
        is_admin=is_admin,
    )

    # tea 1 is admin of wdb
    user = User.objects.get(username=TEACHER_NAME)
    person = NaturalPerson.objects.get_by_user(user)

    org_user = User.objects.get(username=ORGANIZATION_USER_NAME[1])
    org = Organization.objects.get_by_user(org_user)
    pos = 0
    is_admin = 1

    Position.objects.create(
        person=person,
        org=org,
        pos=pos,
        is_admin=is_admin,
    )

    # stu 2 is one of hhb
    user = User.objects.get(username=USER_NAME_2)
    person = NaturalPerson.objects.get_by_user(user)

    org_user = User.objects.get(username=ORGANIZATION_USER_NAME[0])
    org = Organization.objects.get_by_user(org_user)
    pos = 1
    is_admin = 0

    Position.objects.create(
        person=person,
        org=org,
        pos=pos,
        is_admin=is_admin,
    )


def create_activity():
    ...


def create_participant():
    ...

    
def create_semester():
    spring_type = SemesterType.objects.create(ty_name = "春季学期")
    autumn_type = SemesterType.objects.create(ty_name = "秋季学期")
    
    #By default, spring semester is 2.1-6.30, autumn semester is 9.1-1.31
    #For summer vacation, the current semester object falls back to last semester, i.e. spring semester
    today = date.today()
    spring_start = date(today.year, 2, 1)
    if spring_start <= today <= date(today.year, 8, 31):
        #current semester is spring semester
        Semester.objects.bulk_create(
            [
                Semester(year=today.year, ty=spring_type,
                         start_date=spring_start, end_date=date(today.year, 6, 30)),
                Semester(year=today.year, ty=autumn_type,
                         start_date=date(today.year, 9, 1), end_date=date(today.year+1, 1, 31))
            ]
        )
    else:
        #current semester is autumn semester
        #if today.date is before 2.1, then semester's year is today.year-1
        cur_year = today.year if today.month >= 9 else today.year - 1
        Semester.objects.bulk_create(
            [
                Semester(year=cur_year, ty=autumn_type,
                         start_date=date(cur_year, 9, 1), end_date=date(cur_year+1, 1, 31)),
                Semester(year=cur_year+1, ty=spring_type,
                         start_date=date(cur_year+1, 2, 1), end_date=date(cur_year+1, 6, 30))
            ]
        )


def create_all():
    # TODO: Add more
    # delete all
    delete_all()

    # person
    create_superuser()
    create_np()

    # org
    create_org_type()
    create_org_tag()
    create_org()
    create_position()

    # semester
    create_semester()
    



