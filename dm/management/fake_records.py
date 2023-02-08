"""
Generate fake records. Only used in dev & test.
"""

from django.conf import settings


from generic.models import User
from app.models import *

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
    # 先删除所有再创建
    NaturalPerson.objects.all().delete()

    sid = username = "1800017710"
    password = username
    name = "小明"
    gender = NaturalPerson.Gender.MALE
    stu_major = "元培计划（待定）"
    stu_grade = "20" + sid[:2]
    stu_class = 5
    email = sid + "@stu.pku.edu.cn"
    visit_times = 100
    tel = None
    biography = '为按死的鸟发哪家低年级你杀菌灯假设的静安寺的静安寺大石街道'
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
    # 先删除所有再创建
    OrganizationType.objects.all().delete()

    otype_id = 1
    otype_name = '学生小组'
    user = User.objects.get(username='1800017710')
    user.save()

    incharge = NaturalPerson.objects.get_by_user(user)
    job_name_list = ['部长']

    exist = OrganizationType.objects.filter(otype_id=otype_id)
    if len(exist) == 0:
        org_type = OrganizationType.objects.create(
            otype_id=otype_id,
            otype_name=otype_name,
            incharge=incharge,
            job_name_list=job_name_list,
        )
        org_type.save()


def create_org_tag():
    # 先删除所有再创建
    OrganizationTag.objects.all().delete()

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
    # 先删除所有再创建
    Organization.objects.all().delete()

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


def create_activity():
    ...


def create_participant():
    ...


def create_all():
    # 先删除再创建
    User.objects.all().delete()

    # TODO: Add more
    # Order.objects.all().values().delete()
    create_superuser()
    create_np()
    create_org_type()
    create_org_tag()
    create_org()

