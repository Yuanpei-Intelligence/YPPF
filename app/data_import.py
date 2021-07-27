import pandas as pd
import os
from app.models import NaturalPerson, Position, Organization, OrganizationType
from django.contrib.auth.models import User
from django.shortcuts import render, redirect


def load_file(file):
    return pd.read_csv(f"test_data/{file}", dtype=object, encoding="utf-8")


def load_orgtype():
    username = "YPadmin"
    user, mid = User.objects.get_or_create(username=username)
    password = "YPPFtest"
    user.set_password(password)
    user.save()
    Nperson, mid = NaturalPerson.objects.get_or_create(person_id=user)
    Nperson.name = username
    Nperson.save()
    org_type_df = load_file("orgtypeinf.csv")
    for _, otype_dict in org_type_df.iterrows():
        type_id = int(otype_dict["otype_id"])
        type_name = otype_dict["otype_name"]
        # type_superior_id = int(otype_dict["otype_superior_id"])
        incharge = otype_dict["incharge"]
        orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
        orgtype.otype_name = type_name
        # orgtype.otype_superior_id = type_superior_id
        Nperson, mid = NaturalPerson.objects.get_or_create(name=incharge)
        orgtype.incharge = Nperson
        orgtype.job_name_list = otype_dict["job_name_list"]
        orgtype.save()


def load_org():
    org_df = load_file("orginf.csv")
    for _, org_dict in org_df.iterrows():
        username = org_dict["organization_id"]
        if username[:2] == "zz":
            password = "YPPFtest"
            oname = org_dict["oname"]
            type_id = org_dict["otype_id"]
            person = org_dict["person"]
            user, mid = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save()
            orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
            org, mid = Organization.objects.get_or_create(
                organization_id=user, otype=orgtype
            )
            org.oname = oname
            org.save()

            people, mid = NaturalPerson.objects.get_or_create(name=person)
            pos, mid = Position.objects.get_or_create(person=people, org=org)
            pos.save()
            # orgtype=OrganizationType.objects.create(otype_id=type_id)
            # orgtype.otype


def load_org_info(request):
    if request.user.is_superuser:
        load_type = request.GET.get("loadtype", None)
        message = "加载失败！"
        if load_type is None:
            message = "没有传入loadtype参数:[org或otype]"
        elif load_type == "otype":
            load_orgtype()
            message = "导入组织类型信息成功！"
        elif load_type == "org":
            load_org()
            message = "导入组织信息成功！"
        else:
            message = "没有得到loadtype参数:[org或otype]"
    else:
        message = "请先以超级账户登录后台后再操作！"
    return render(request, "debugging.html", locals())


def load_stu_info(request):
    if request.user.is_superuser:
        stu_df = load_file("stuinf.csv")
        for _, stu_dict in stu_df.iterrows():
            sid = username = stu_dict["学号"]
            password = username
            name = stu_dict["姓名"]
            gender = stu_dict["性别"]
            stu_major = stu_dict["专业"]
            stu_grade = "20" + sid[0:2]
            stu_class = stu_dict["班级"]
            email = stu_dict["邮箱"]
            if email == "None":
                if sid[0] == "2":
                    email = sid + "@stu.pku.edu.cn"
                else:
                    email = sid + "@pku.edu.cn"
            tel = stu_dict["手机号"]

            user = User.objects.create(username=username)
            user.set_password(password)
            user.save()
            stu = NaturalPerson.objects.create(person_id=user)
            stu.name = name
            if gender == "男":
                stu.gender = NaturalPerson.Gender.MALE
            elif gender == "女":
                stu.gender = NaturalPerson.Gender.FEMALE
            else:
                stu.gender = NaturalPerson.Gender.OTHER
            stu.stu_major = stu_major
            stu.stu_grade = stu_grade
            stu.stu_class = stu_class

            stu.email = email
            stu.telephone = tel
            stu.save()
        message = "导入学生信息成功！"
    else:
        message = "请先以超级账户登录后台后再操作！"
    return render(request, "debugging.html", locals())
