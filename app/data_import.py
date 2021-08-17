from app.models import TransferRecord
from app.models import Notification
import pandas as pd
import os
from app.models import NaturalPerson, Position, Organization, OrganizationType,Activity
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from tqdm import tqdm
import math
from datetime import datetime
from boottest import local_dict
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
        password = "YPPFtest"
        if username[:2] == "zz":
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
            pos, mid = Position.objects.get_or_create(person=people, org=org, status=Position.Status.INSERVICE, pos=0)
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

def load_activity_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    act_df=load_file("activityinfo.csv")
    act_list = []
    for _, act_dict in act_df.iterrows():
        organization_id = str(act_dict["organization_id"])

        try:
            user = User.objects.get(username=organization_id)
            org=Organization.objects.get(organization_id=user)
        except:
            context = {"message": "请先导入组织信息！{username}".format(username=organization_id)}
            return render(request, "debugging.html", context)
        title=act_dict['title']
        start=act_dict['start']
        end=act_dict['end']
        start=datetime.strptime(start, '%m/%d/%Y %H:%M %p')
        end=datetime.strptime(end, '%m/%d/%Y %H:%M %p')
        location=act_dict['location']
        introduction=act_dict['introduction']
        YQPoint=float(act_dict['YQPoint'])
        capacity=int(act_dict['capacity'])
        URL=act_dict['URL']

        act_list.append(
            Activity(
                title=title,
                organization_id=org,
                start=start,
                end=end,
                location=location,
                introduction=introduction,
                YQPoint=YQPoint,
                capacity=capacity,
                URL=URL
            )
        )
    Activity.objects.bulk_create(act_list)
    context = {"message": "导入活动信息成功！"}
    return render(request, "debugging.html", context)

def load_transfer_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    act_df=load_file("transferinfo.csv")
    act_list = []
    for _, act_dict in act_df.iterrows():
        id = act_dict['id']
        status=act_dict['status']
        start_time=str(act_dict['start_time'])
        finish_time=str(act_dict['finish_time'])
        start_time=datetime.strptime(start_time, "%d/%m/%Y %H:%M:%S.%f")
        try:
            finish_time=datetime.strptime(finish_time, "%d/%m/%Y %H:%M:%S.%f")
        except:
            finish_time=None
        message=act_dict['message']
        amount=float(act_dict['amount'])
        if str(act_dict['proposer_id']) == str(1266):
            act_dict['proposer_id'] = NaturalPerson.objects.get(name=local_dict['test_info']['stu_name']).person_id.id
        if str(act_dict['recipient_id']) == str(1266):
            act_dict['recipient_id'] = NaturalPerson.objects.get(name=local_dict['test_info']['stu_name']).person_id.id
        proposer=User.objects.get(id=act_dict['proposer_id'])
        recipient=User.objects.get(id=act_dict['recipient_id'])
        try:
            corres_act=Activity.objects.get(id=act_dict['corres_act_id'])
        except:
            corres_act=None
        act_list.append(
            TransferRecord(
                id=id,
                status=status,
                start_time=start_time,
                finish_time=finish_time,
                message=message,
                amount=amount,
                proposer=proposer,
                recipient=recipient,
                corres_act=corres_act
            )
        )
    TransferRecord.objects.bulk_create(act_list)
    context = {"message": "导入转账信息成功！"}
    return render(request, "debugging.html", context)

def load_notification_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    not_df=load_file("notificationinfo.csv")
    not_list = []
    for _, not_dict in not_df.iterrows():
        id = not_dict["id"]
        if str(not_dict['receiver_id']) == str(1266):
            not_dict['receiver_id'] = NaturalPerson.objects.get(name=local_dict['test_info']['stu_name']).person_id.id
        if str(not_dict['sender_id']) == str(1266):
            not_dict['sender_id'] = NaturalPerson.objects.get(name=local_dict['test_info']['stu_name']).person_id.id
        try:
            receiver = User.objects.get(id=not_dict["receiver_id"])
            sender = User.objects.get(id=not_dict["sender_id"])
        except:
            context = {"message": "请先导入用户信息！{username1} & {username2}".format(username1=receiver,username2=sender)}
            return render(request, "debugging.html", context)
        status=not_dict['status']
        title=not_dict['title']
        start_time=str(not_dict['start_time'])
        finish_time=str(not_dict['finish_time'])
        start_time=datetime.strptime(start_time, "%d/%m/%Y %H:%M:%S.%f")
        try:
            finish_time=datetime.strptime(finish_time, "%d/%m/%Y %H:%M:%S.%f")
        except:
            finish_time=None
        content=not_dict['content']
        typename=not_dict['typename']
        URL=not_dict['URL']
        try:
            relate_TransferRecord = TransferRecord.objects.get(id=not_dict['relate_TransferRecord_id'])
        except:
            relate_TransferRecord = None
        not_list.append(
            Notification(
                id=id,
                receiver=receiver,
                sender=sender,
                status=status,
                title=title,
                start_time=start_time,
                finish_time=finish_time,
                content=content,
                URL=URL,
                typename=typename,
                relate_TransferRecord=relate_TransferRecord
            )
        )
    Notification.objects.bulk_create(not_list)
    context = {"message": "导入通知信息成功！"}
    return render(request, "debugging.html", context)

def load_stu_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)

    stu_df = load_file("stuinf.csv")
    stu_list = []
    Char2Gender = {"男": NaturalPerson.Gender.MALE, "女": NaturalPerson.Gender.FEMALE}
    for _, stu_dict in tqdm(stu_df.iterrows()):
        sid = username = stu_dict["学号"]
        password = username
        name = stu_dict["姓名"]
        gender = Char2Gender[stu_dict["性别"]]
        stu_major = stu_dict["专业"]
        stu_grade = "20" + sid[:2]
        stu_class = stu_dict["班级"]
        email = stu_dict["邮箱"]
        if email == "None":
            if sid[0] == "2":
                email = sid + "@stu.pku.edu.cn"
            else:
                email = sid + "@pku.edu.cn"
        tel = stu_dict["手机号"]

        user = User.objects.create(username=username)
        user.set_password(password)  # 这一步的PBKDF2加密算法太慢了
        user.save()

        # 批量导入比循环导入快很多，但可惜由于外键person_id的存在，必须先保存user，User模型无法批量导入。
        # 但重点还是 set_password 的加密算法太 TM 的慢了！
        stu_list.append(
            NaturalPerson(
                person_id=user,
                name=name,
                gender=gender,
                stu_major=stu_major,
                stu_grade=stu_grade,
                stu_class=stu_class,
                email=email,
                telephone=tel,
            )
        )
    NaturalPerson.objects.bulk_create(stu_list)

    context = {"message": "导入学生信息成功！"}
    return render(request, "debugging.html", context)

