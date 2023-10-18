"""
Generate fake records. Only used in dev & test.
"""

from datetime import date

from generic.models import User
from app.models import *
from semester.models import Semester, SemesterType
from boot import config
from utils.marker import fix_me

UIDS = ["1", "2"]
TEACHER_UIDS = ["10", "11"]

ORG_UIDS = ['zz00001', 'zz00002', 'zz00000']
ORG_NAMES = ['绘画班', '舞蹈班', 'Official']


# TODO: Change Settings
assert config.DEBUG, 'Should not import fake_records in production env.'


def delete_all():
    User.objects.all().delete()
    OrganizationType.objects.all().delete()
    OrganizationTag.objects.all().delete()


def create_superuser():
    User.objects.create_superuser('admin', '管理员', password='admin')


@fix_me
def _create_old_user(username, password, usertype):
    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_newuser = False
    user.utype = usertype
    user.save()
    return user, created


def create_np():
    uid, name = UIDS[0], '1号学生'
    user, created = _create_old_user(uid, uid, User.Type.PERSON)
    if created:
        NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=uid,
            name=name,
            gender=NaturalPerson.Gender.MALE,
            stu_major='元培计划（待定）',
            stu_grade='2020',
            stu_class=5,
            email=uid + '@stu.pku.edu.cn',
            telephone=None,
            visit_times=100,
            biography='我是1号学生',
            identity=NaturalPerson.Identity.STUDENT,
        )

    uid, name = UIDS[1], '2号学生'
    user, created = _create_old_user(uid, uid, User.Type.PERSON)
    if created:
        NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=uid,
            name=name,
            gender=NaturalPerson.Gender.FEMALE,
            stu_major='元培计划（待定）',
            stu_grade='2020',
            stu_class=5,
            email=uid + '@stu.pku.edu.cn',
            telephone=None,
            visit_times=100,
            biography='我是2号学生',
            identity=NaturalPerson.Identity.STUDENT,
        )

    uid, name = TEACHER_UIDS[0], '1号老师'
    user, created = _create_old_user(uid, uid, User.Type.PERSON)
    if created:
        NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=uid,
            name=name,
            gender=NaturalPerson.Gender.MALE,
            email=uid + '@pku.edu.cn',
            telephone=None,
            visit_times=100,
            biography='我是1号老师',
            identity=NaturalPerson.Identity.TEACHER,
        )

    uid, name = TEACHER_UIDS[1], '2号老师'
    user, created = _create_old_user(uid, uid, User.Type.PERSON)
    if created:
        NaturalPerson.objects.create(
            person_id=user,
            stu_id_dbonly=uid,
            name=name,
            gender=NaturalPerson.Gender.MALE,
            email=uid + '@pku.edu.cn',
            telephone=None,
            visit_times=100,
            biography='我是2号老师',
            identity=NaturalPerson.Identity.TEACHER,
        )


def create_org_type():
    otype_id = 1
    otype_name = '学生小组'

    user = User.objects.get(username=UIDS[0])
    incharge = NaturalPerson.objects.get_by_user(user)

    job_name_list = ['部长', '副部长', '部员']

    org_type = OrganizationType.objects.create(
        otype_id=otype_id,
        otype_name=otype_name,
        incharge=incharge,
        job_name_list=job_name_list,
    )


def create_org_tag():
    OrganizationTag.objects.create(
        name='兴趣',
        color=OrganizationTag.ColorChoice.red
    )
    OrganizationTag.objects.create(
        name='住宿生活',
        color=OrganizationTag.ColorChoice.blue
    )


def create_org():

    for uname, oname in zip(ORG_UIDS, ORG_NAMES):
        otype = OrganizationType.objects.get(otype_id=1)
        tags = OrganizationTag.objects.get(name='兴趣')
        user, created = _create_old_user(uname, uname, User.Type.ORG)

        if created:
            org = Organization.objects.create(
                organization_id=user,
                oname=oname,
                otype=otype,
            )
            org.tags.set([tags])
            org.save()


def _create_position(person_uid, org_uid, pos, is_admin):
    user = User.objects.get_user(person_uid)
    person = NaturalPerson.objects.get_by_user(user)

    org_user = User.objects.get_user(org_uid)
    org = Organization.objects.get_by_user(org_user)

    Position.objects.create(
        person=person,
        org=org,
        pos=pos,
        is_admin=is_admin,
    )


def create_position():
    # stu 1 is admin of hhb
    _create_position(UIDS[0], ORG_UIDS[0], 0, True)

    # stu 1 is one of wdb
    _create_position(UIDS[0], ORG_UIDS[1], 1, False)

    # tea 1 is admin of wdb
    _create_position(TEACHER_UIDS[0], ORG_UIDS[1], 0, True)

    # stu 2 is one of hhb
    _create_position(UIDS[1], ORG_UIDS[0], 1, False)


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
