"""
Generate fake records. Only used in dev & test.
"""

from django.conf import settings

from generic.models import User
from app.models import NaturalPerson

# TODO: Change Settings
assert settings.DEBUG, 'Should not import fake_records in production env.'


def create_superuser():
    try:
        User.objects.create_superuser(username='admin', password='admin',
                                      email='admin@notexist.com')
    except:
        pass


def create_np():
    # TODO: Modify it
    sid = username = "2000000000"
    password = username
    name = "小明"
    gender = NaturalPerson.Gender.MALE
    stu_major = "元培计划（待定）"
    stu_grade = "20" + sid[:2]
    stu_class = 5
    email = sid + "@stu.pku.edu.cn"
    tel = None

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
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
        )
        stu.save()


def create_org_ty():
    ...


def create_org():
    ...


def create_activity():
    ...


def create_participant():
    ...


def create_all():
    # TODO: Add more
    create_superuser()
    create_np()
