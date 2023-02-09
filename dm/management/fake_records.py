"""
Generate fake records. Only used in dev & test.
"""

from django.conf import settings
from generic.models import User
from app.models import *

USER_NAME = "2000000000"

# TODO: Change Settings
assert settings.DEBUG, 'Should not import fake_records in production env.'


def delete_all():
    User.objects.all().delete()
    NaturalPerson.objects.all().delete()
    OrganizationType.objects.all().delete()
    OrganizationTag.objects.all().delete()
    Organization.objects.all().delete()





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
    name = "小明"
    gender = NaturalPerson.Gender.MALE
    stu_major = "元培计划（待定）"
    stu_grade = "20" + sid[:2]
    stu_class = 5
    email = sid + "@stu.pku.edu.cn"
    visit_times = 100
    tel = None
    biography = '各位考官好，今天能够站在这里参加面试，有机会向各位考官请教和学习，' \
                '我感到非常的荣幸。希 望通过这次面试能够把自己展示给大家，希望大家记住我。' \
                '我叫xxx，今年xx岁。汉族，法学本科。我 平时喜欢看书和上网浏览信息。我的性格比较开朗，' \
                '随和。能关系周围的任何事，和亲人朋友能够和睦 相处，并且对生活充满了信心。我以前在检察院实习过，' \
                '所以有一定的实践经验。在外地求学的四年 中，我养成了坚强的性格，这种性格使我克服了学习和生活中的一些困难，' \
                '积极进去。成为一名法律工 作者是我多年以来的强烈愿望。'
    first_time_login = False

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.first_time_login = first_time_login
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
        )
        stu.save()


def create_org_type():
    otype_id = 1
    otype_name = '学生小组'
    user = User.objects.get(username=USER_NAME)

    incharge = NaturalPerson.objects.get_by_user(user)
    job_name_list = ['部长']

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
    username='huihuaban'
    user, created = User.objects.get_or_create(username=username)
    user.utype = User.Type.ORG
    oname = '绘画班'
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

    username_2='wudaoban'
    user_2, created_2 = User.objects.get_or_create(username=username_2)
    user_2.utype = User.Type.ORG
    oname_2 = '舞蹈班'
    otype_2 = OrganizationType.objects.get(otype_id=1)
    tags_2 = OrganizationTag.objects.get(name='兴趣')
    tags_2_2 = OrganizationTag.objects.get(name='住宿生活')
    user_2.save()

    if created_2:
        org_2 = Organization.objects.create(
            organization_id=user_2,
            oname=oname_2,
            otype=otype_2,
        )
        org_2.tags.set([tags_2, tags_2_2])
        org_2.save()


def create_position():
    user = User.objects.get(username=USER_NAME)

    person =


def create_activity():
    ...


def create_participant():
    ...


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




