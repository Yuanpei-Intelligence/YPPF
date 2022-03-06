from app.constants import *
from app.models import (
    NaturalPerson,
    Freshman,
    Position,
    Organization,
    OrganizationTag,
    OrganizationType,
    Activity,
    TransferRecord,
    Notification,
    Help,
    Course,
    CourseRecord,
    Semester,
    FeedbackType,
    Feedback,
    Comment,
)
from app.utils import random_code_init, get_user_by_name

import os
import math
import json
import numpy
import pandas as pd
from tqdm import tqdm
from datetime import datetime

from boottest import local_dict
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.db import transaction

__all__ = [
    # utils
    'create_user', 'create_person', 'create_org',
    'create_person_account', 'create_org_account',
    # basic loads
    'load_stu', 'load_orgtype', 'load_org',
    # basic views
    'load_stu_data', 'load_org_data',
    # views
    'load_freshman_info', 'load_help', 'load_org_tag',
    'load_tags_for_old_org', 'load_course_record',
    # debugs
    'load_activity_info', 'load_transfer_info', 'load_notification_info',
    'load_feedback_type', 'load_feedback', 'load_feedback_comments',
    'load_feedback_data',
]


# local tools
def create_user(id, rand_pw=False, reset_pw=None, **defaults):
    '''create user locally'''
    try:
        stage = 'convert userid'
        id = str(id)
        stage = 'create user'
        user, created = User.objects.get_or_create(
            username=id, defaults=defaults)
        if created or reset_pw is not None:
            stage = 'get password'
            password = reset_pw
            if not isinstance(password, str):
                password = random_code_init(id) if rand_pw else id
            stage = 'set password'
            user.set_password(password)
            user.save()
        return user
    except RuntimeError: raise
    except: raise RuntimeError(f'{stage} failed')


def create_person(name, user, **defaults):
    '''create naturalperson locally, but why not call `get_or_create`?'''
    try:
        stage = 'get user'
        user = user if isinstance(user, User) else User.objects.get(username=user)
        stage = 'create naturalperson'
        person, created = NaturalPerson.objects.get_or_create(
            person_id=user, name=name, defaults=defaults)
        return person
    except RuntimeError: raise
    except: raise RuntimeError(f'{stage} failed')


def create_org(name, user, otype, **defaults):
    '''create organization locally, but why not call `get_or_create`?'''
    try:
        stage = 'get user'
        user = user if isinstance(user, User) else User.objects.get(username=user)
        stage = 'get organization type'
        if not isinstance(otype, OrganizationType):
            if isinstance(otype, int):
                otype = OrganizationType.objects.get(pk=otype)
            elif OrganizationType.objects.filter(otype_name=otype).exists():
                otype = OrganizationType.objects.get(otype_name=otype)
            else:
                otype = OrganizationType.objects.get(otype_name__contains=otype)
        stage = 'create organization'
        org, created = Organization.objects.get_or_create(
            organization_id=user, oname=name, otype=otype, defaults=defaults)
        return org
    except RuntimeError: raise
    except: raise RuntimeError(f'{stage} failed')


def create_person_account(name, pid, rand_pw=False, reset_pw=None, **defaults):
    '''create person user locally'''
    user = create_user(pid, rand_pw=rand_pw, reset_pw=reset_pw)
    person = create_person(name, user, **defaults)
    return person


def create_org_account(name, oid, otype, rand_pw=False, reset_pw=None, **defaults):
    '''create organization user locally'''
    user = create_user(oid, rand_pw=rand_pw, reset_pw=reset_pw)
    org = create_org(name, user, otype, **defaults)
    return org


def load_file(file):
    return pd.read_csv(f"test_data/{file}", dtype=object, encoding="utf-8")


def load_stu_data(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    return render(request, "debugging.html", load_stu())


def load_orgtype(debug=True):
    if debug:
        username = "someone"
        user, mid = User.objects.get_or_create(username=username)
        password = random_code_init(username)
        user.set_password(password)
        user.save()

        Nperson, mid = NaturalPerson.objects.get_or_create(person_id=user)
        Nperson.name = "待定"
        Nperson.save()
    org_type_df = load_file("orgtypeinf.csv")
    for _, otype_dict in org_type_df.iterrows():
        type_id = int(otype_dict["otype_id"])
        type_name = otype_dict["otype_name"]
        control_pos_threshold = int(otype_dict.get("control_pos_threshold", 0))
        # type_superior_id = int(otype_dict["otype_superior_id"])
        incharge = otype_dict.get("incharge", "待定")
        orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
        orgtype.otype_name = type_name
        # orgtype.otype_superior_id = type_superior_id
        try:
            Nperson, mid = NaturalPerson.objects.get(name=incharge)
        except:
            user, mid = User.objects.get_or_create(username=incharge)
            Nperson, mid = NaturalPerson.objects.get_or_create(person_id=user)
        orgtype.incharge = Nperson
        orgtype.job_name_list = otype_dict["job_name_list"]
        orgtype.control_pos_threshold = control_pos_threshold
        orgtype.save()


def load_org():
    org_df = load_file("orginf.csv")
    msg = ''
    for _, org_dict in org_df.iterrows():
        try:
            username = org_dict.get("organization_id", "")
            if not isinstance(username, str):
                # 如果该列存在但行无数据，会得到numpy.nan: float
                username = ""
            password = 'YPPFtest' if DEBUG else random_code_init(username)
            # 现在找不到直接出错
            org_found = True
            if username[:2] == "zz":
                oname = org_dict["oname"]
                type_id = org_dict["otype_id"]
                user, created = User.objects.get_or_create(username=username)
                if created:
                    user.set_password(password)
                    user.save()
                # 组织类型必须已经创建
                orgtype = OrganizationType.objects.get(otype_id=type_id)
                org, created = Organization.objects.get_or_create(
                    organization_id=user, otype=orgtype
                )
                org.oname = oname
                org.save()
                msg += '<br/>成功创建组织：'+oname
            # 否则不会创建用户，只会查找或修改已有的组织
            else:
                # 先尝试以组织名检索
                oname = username
                orgs = Organization.objects.filter(oname=oname)
                if not len(orgs):
                    orgs = Organization.objects.filter(oname__contains=oname)
                oname = org_dict["oname"]
                if len(orgs) == 1:
                    # 如果只有一个，一定是所需的组织，重命名
                    org = orgs.first()
                    origin_oname = org.oname
                    org.oname = oname
                    org.save()
                    msg += f'<br/>重命名组织：{origin_oname}->{oname}'
                else:
                    # 直接读取名称
                    orgs = Organization.objects.filter(oname=oname)
                    if not len(orgs):
                        orgs = Organization.objects.filter(oname__contains=oname)
                    assert len(orgs) == 1, f'未找到组织：{oname}'
                    org = orgs[0]
                    oname = org.oname
                    msg += f'<br/>检索到已存在组织：{oname}'

            if org_found:
                # 必须是本学期的才更新，否则创建
                all_positions = Position.objects.current()
                pos = max(0, int(org_dict.get("pos", 0)))
                pos_display = org.otype.get_name(pos)
                persons = org_dict.get("person", "待定")
                if not isinstance(persons, str):
                    # 如果该列存在但行无数据，会得到numpy.nan: float
                    persons = ""
                for person in persons.split(','):
                    people = NaturalPerson.objects.get(name=person)
                    # 获得其当前的职位
                    get_kws = dict(person=people, org=org)
                    position, created = all_positions.get_or_create(**get_kws)
                    # 更新为可用职位
                    position.status = Position.Status.INSERVICE
                    position.pos = pos
                    position.is_admin = org.otype.default_is_admin(pos)
                    if created:
                        # 书院课程以学期为单位更新
                        position.in_semester = org.otype.default_semester()
                    position.save()
                    msg += f'<br/>&emsp;&emsp;成功增加{pos_display}：{person}'
        except Exception as e:
            msg += '<br/>未能创建组织'+oname+',原因：'+str(e)
    if YQP_ONAME:
        username = 'zz00001'
        user, created = User.objects.get_or_create(username=username)
        if created:
            password = random_code_init(username)
            user.set_password(password)
            user.save()
            orgtype, mid = OrganizationType.objects.get_or_create(otype_id=0)
            org, mid = Organization.objects.get_or_create(
                organization_id=user, otype=orgtype
            )
            org.oname = YQP_ONAME
            org.save()
            msg += '<br/>成功创建元气值发放组织：'+YQP_ONAME
    return msg


def load_org_data(request):
    if request.user.is_superuser:
        load_type = request.GET.get("loadtype", None)
        message = "加载失败！"
        if load_type is None:
            message = "没有传入loadtype参数:[org或otype]"
        elif load_type == "otype":
            load_orgtype()
            message = "导入小组类型信息成功！"
        elif load_type == "org":
            message = "导入小组信息成功！"+load_org()
        else:
            message = "没有得到loadtype参数:[org或otype]"
    else:
        message = "请先以超级账户登录后台后再操作！"
    return render(request, "debugging.html", locals())


def load_activity_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    act_df = load_file("activityinfo.csv")
    act_list = []
    for _, act_dict in act_df.iterrows():
        organization_id = str(act_dict["organization_id"])

        try:
            user = User.objects.get(username=organization_id)
            org = Organization.objects.get(organization_id=user)
        except:
            context = {
                "message": "请先导入小组信息！{username}".format(username=organization_id)
            }
            return render(request, "debugging.html", context)
        title = act_dict["title"]
        start = act_dict["start"]
        end = act_dict["end"]
        start = datetime.strptime(start, "%m/%d/%Y %H:%M %p")
        end = datetime.strptime(end, "%m/%d/%Y %H:%M %p")
        location = act_dict["location"]
        introduction = act_dict["introduction"]
        YQPoint = float(act_dict["YQPoint"])
        capacity = int(act_dict["capacity"])
        URL = act_dict["URL"]

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
                URL=URL,
                examine_teacher = NaturalPerson.objects.get(name="YPadmin")
            )
        )
    # Activity.objects.bulk_create(act_list)
    for act in act_list:
        act.save()
    context = {"message": "导入活动信息成功！"}
    return render(request, "debugging.html", context)


def load_transfer_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    act_df = load_file("transferinfo.csv")
    act_list = []
    for _, act_dict in act_df.iterrows():
        id = act_dict["id"]
        status = act_dict["status"]
        start_time = str(act_dict["start_time"])
        finish_time = str(act_dict["finish_time"])
        start_time = datetime.strptime(start_time, "%d/%m/%Y %H:%M:%S.%f")
        try:
            finish_time = datetime.strptime(finish_time, "%d/%m/%Y %H:%M:%S.%f")
        except:
            finish_time = None
        message = act_dict["message"]
        amount = float(act_dict["amount"])
        if str(act_dict["proposer_id"]) == str(1266):
            act_dict["proposer_id"] = NaturalPerson.objects.get(
                name=local_dict["test_info"]["stu_name"]
            ).person_id.id
        if str(act_dict["recipient_id"]) == str(1266):
            act_dict["recipient_id"] = NaturalPerson.objects.get(
                name=local_dict["test_info"]["stu_name"]
            ).person_id.id
        proposer = User.objects.get(id=act_dict["proposer_id"])
        recipient = User.objects.get(id=act_dict["recipient_id"])
        try:
            corres_act = Activity.objects.get(id=act_dict["corres_act_id"])
        except:
            corres_act = None
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
                corres_act=corres_act,
            )
        )
    TransferRecord.objects.bulk_create(act_list)
    context = {"message": "导入转账信息成功！"}
    return render(request, "debugging.html", context)


def load_notification_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    not_df = load_file("notificationinfo.csv")
    not_list = []
    for _, not_dict in not_df.iterrows():
        id = not_dict["id"]
        if str(not_dict["receiver_id"]) == str(1266):
            not_dict["receiver_id"] = NaturalPerson.objects.get(
                name=local_dict["test_info"]["stu_name"]
            ).person_id.id
        if str(not_dict["sender_id"]) == str(1266):
            not_dict["sender_id"] = NaturalPerson.objects.get(
                name=local_dict["test_info"]["stu_name"]
            ).person_id.id
        try:
            receiver = User.objects.get(id=not_dict["receiver_id"])
            sender = User.objects.get(id=not_dict["sender_id"])
        except:
            context = {
                "message": "请先导入用户信息！{username1} & {username2}".format(
                    username1=receiver, username2=sender
                )
            }
            return render(request, "debugging.html", context)
        status = not_dict["status"]
        title = not_dict["title"]
        start_time = str(not_dict["start_time"])
        finish_time = str(not_dict["finish_time"])
        start_time = datetime.strptime(start_time, "%d/%m/%Y %H:%M:%S.%f")
        try:
            finish_time = datetime.strptime(finish_time, "%d/%m/%Y %H:%M:%S.%f")
        except:
            finish_time = None
        content = not_dict["content"]
        typename = not_dict["typename"]
        URL = not_dict["URL"]
        try:
            relate_TransferRecord = TransferRecord.objects.get(
                id=not_dict["relate_TransferRecord_id"]
            )
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
                relate_TransferRecord=relate_TransferRecord,
            )
        )
    Notification.objects.bulk_create(not_list)
    context = {"message": "导入通知信息成功！"}
    return render(request, "debugging.html", context)


def load_stu():
    stu_df = load_file("stuinf.csv")
    total = 0
    stu_list = []
    exist_list = []
    failed_list = []
    Char2Gender = {"男": NaturalPerson.Gender.MALE, "女": NaturalPerson.Gender.FEMALE}
    username = 'null'
    fail_info = None
    for _, stu_dict in tqdm(stu_df.iterrows()):
        total += 1
        try:
            sid = username = stu_dict["学号"]
            password = username
            name = stu_dict["姓名"]
            gender = Char2Gender[stu_dict["性别"]]
            stu_major = stu_dict["专业"]
            if not stu_major or stu_major == "None":
                stu_major = "元培计划（待定）"
            stu_grade = "20" + sid[:2]
            stu_class = stu_dict["班级"]
            email = stu_dict["邮箱"]
            if not email or email == "None":
                if sid[0] == "2":
                    email = sid + "@stu.pku.edu.cn"
                else:
                    email = sid + "@pku.edu.cn"
            tel = stu_dict["手机号"]
            if not tel or tel == "None":
                tel = None

            user, created = User.objects.get_or_create(username=username)
            if not created:
                exist_list.append(username)
                continue
            # 这一步的PBKDF2加密算法太慢了
            else:
                # 设置密码
                user.set_password(password)
                user.save()

            # 批量导入比循环导入快很多，但可惜由于外键person_id的存在，必须先保存user，User模型无法批量导入。
            # 但重点还是 set_password 的加密算法太 TM 的慢了！
            stu_list.append(
                NaturalPerson(
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
            )
        except Exception as e:
            fail_info = str(e)
            failed_list.append(username)
            continue
    NaturalPerson.objects.bulk_create(stu_list)

    context = {
        "message": '<br/>'.join((
                    "导入学生信息成功！",
                    f"共{total}人，尝试导入{len(stu_list)}人",
                    f"已存在{len(exist_list)}人，名单为",
                    ','.join(exist_list),
                    f"失败{len(failed_list)}人，名单为",
                    ','.join(failed_list),
                    f'最后一次失败原因为: {fail_info}' if fail_info is not None else '',
                    ))
        }
    return context


def load_freshman_info(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)

    freshman_df = load_file("freshman.csv")
    freshman_list = []
    for _, freshman_dict in tqdm(freshman_df.iterrows()):
        sid = freshman_dict["学号"]
        name = freshman_dict["姓名"]
        gender = freshman_dict["性别"]
        birthday = datetime.strptime(freshman_dict["生日"], "%Y/%m/%d").date()
        place = freshman_dict["生源地"]
        grade = freshman_dict.get("年级", "20" + sid[:2])

        freshman_list.append(
            Freshman(
                sid=sid,
                name=name,
                gender=gender,
                birthday=birthday,
                place=place,
                grade=grade,
                status=Freshman.Status.UNREGISTERED
            )
        )
    Freshman.objects.bulk_create(freshman_list)

    context = {"message": "导入新生信息成功！"}
    return render(request, "debugging.html", context)


def load_help(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    try:
        help_df = load_file("help.csv")
    except:
        context = {"message": "没有找到help.csv,请确认该文件已经在test_data中。"}
        return render(request, "debugging.html", context)
    # helps = [Help(title=title, content=content) for title, content in help_dict.items()]
    for _, help_dict in help_df.iterrows():
        content = help_dict["content"]
        title = help_dict["title"]
        new_help, mid = Help.objects.get_or_create(title=title)
        new_help.content = content
        new_help.save()
    context = {"message": "成功导入帮助信息！"}
    return render(request, "debugging.html", context)


def load_course_record(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    try:
        courserecord_file = pd.read_excel(f"test_data/courtime.xlsx", sheet_name=None)
    except:
        context = {"message": "没有找到courtime.xlsx,请确认该文件已经在test_data中。"}
        return render(request, "debugging.html", context)

    # 学年，学期和课程的德智体美劳信息都是在文件的info这个sheet中读取的
    year = courserecord_file['info'].iloc[1,1]
    semester = courserecord_file['info'].iloc[2,1]
    semester = Semester.get(semester)

    course_type_all = {
       "德" : Course.CourseType.MORAL ,
       "智" : Course.CourseType.INTELLECTUAL ,
       "体" : Course.CourseType.PHYSICAL ,
       "美" : Course.CourseType.AESTHETICS,
       "劳" : Course.CourseType.LABOUR,
    }
    course_info = courserecord_file['info'] #info这个sheet
    info_height, info_width = course_info.shape
    # ---- 以下为读取info里面的课程信息并自动注册course ------
    for i in range(4, info_height):
        course_name = course_info.iloc[i,0]
        course_type = course_info.iloc[i,1] #德智体美劳
        #备注：由于一些课程名称所包含的符号不能被包含在excel文件的sheet的命名中（会报错），
        #所以考虑到这种情况，使用模糊查询的方式，sheet的命名只写一部分就可以了
        orga_found = Organization.objects.filter(oname=course_name)
        if not orga_found.exists(): #若查询不到，使用模糊查询
            orga_found = Organization.objects.filter(oname__contains=course_name)

        if orga_found.exists():
            course_found = Course.objects.filter(
                name = orga_found[0].oname,
                type__in = Course.CourseType,
                year = year,
                semester = semester,
            )
            if not course_found.exists():  #新建课程
                Course.objects.create(
                    name = orga_found[0].oname,
                    organization = orga_found[0],
                    type = course_type_all[course_type],
                    status = Course.Status.END,
                    year = year,
                    semester = semester,
                    photo = (
                        '/static/assets/img/announcepics/'
                        f'{course_type_all[course_type].value+1}.JPG'
                    ),
                )

    # ---- 以下为读取其他sheet并导入学时记录   -------
    info_show = {  #储存异常信息
        'type error': [],
        'stuID miss' :[],
        'person not found' : [],
        'course not found' : [],
        'data miss':[],
    }

    for course in courserecord_file.keys():  #遍历各个sheet
        if course in ['汇总','info']: continue

        course_df = courserecord_file[course] #文件里的一个sheet
        height, width = course_df.shape
        course_found = False   #是否查询到sheet名称所对应的course

        course_get = Course.objects.filter(
            name=course,
            year=year,
            semester=semester,
        )
        if not course_get.exists():
            course_get = Course.objects.filter(
                name__contains=course,
                year=year,
                semester=semester,
            )

        if course_get.exists():  #查找到了相应course
            course_found = True
        else:
            info_show["course not found"].append(course)

        for i in range(4,height):
            #每个sheet开头有几行不是学时信息，所以跳过
            sid: str = course_df.iloc[i, 1]  #学号
            name: str = course_df.iloc[i, 2]
            times: int = course_df.iloc[i, 3]
            hours: float = course_df.iloc[i, 4]
            record_view = f'{course} {sid} {name} {times} {hours}'
            if not isinstance(name, str) and sid is numpy.nan: #允许中间有空行
                continue
            if times is numpy.nan or hours is numpy.nan:  #次数和学时缺少
                info_show["data miss"].append(record_view)
                continue
            try:
                sid = '' if sid is numpy.nan else str(int(float(sid)))
                times, hours = int(times), float(hours)
                name = str(name)
            except:
                info_show["type error"].append(record_view)
                continue

            person = NaturalPerson.objects.filter(name=name)
            if not sid:  #没有学号
                info_show["stuID miss"].append(record_view)
            else:  #若有学号，则根据学号继续查找（排除重名）
                person = person.filter(person_id__username=sid)

            if not person.exists():
                error_info = [record_view]
                #若同时按照学号和姓名查找不到的话，则只用姓名或者只用学号查找可能的人员
                person_guess_byname = NaturalPerson.objects.filter(name=name)
                if sid:  #若填了学号的话，则试着查找
                    person_guess_byId = NaturalPerson.objects.filter(
                        person_id__username=sid)
                else:
                    person_guess_byId = None
                error_info += [person_guess_byname, person_guess_byId]
                info_show["person not found"].append(error_info)
                continue

            record = CourseRecord.objects.filter(  #查询是否已经有记录
                person=person[0],
                year=year,
                semester=semester,
            )
            record_search_course = record.filter(course__name=course)
            record_search_extra = record.filter(extra_name=course)
            # 需要时临时修改即可
            invalid = float(hours) < LEAST_RECORD_HOURS

            if record_search_course.exists():
                record_search_course.update(
                    invalid = invalid,
                    attend_times = times,
                    total_hours = hours
                )
            elif record_search_extra.exists():
                record_search_extra.update(
                    invalid = invalid,
                    attend_times = times,
                    total_hours = hours
                )
            else:
                newrecord = CourseRecord.objects.create(
                    person = person[0],
                    extra_name = course,
                    attend_times = times,
                    total_hours = hours,
                    year = year,
                    semester = semester,
                    invalid = invalid,
                )
                if course_found:
                    newrecord.course = course_get[0]
                    newrecord.save()

    # ----- 以下为前端展示导入的结果 ------
    display_message = '导入完成\n'
    print_show = [
        '<br><div style="color:blue;">未查询到该人员：</div>',
        '<div style="color:blue;">是不是想导入以下学生？：</div>',
        '<div style="color:blue;">未查询到以下课程，已通过额外字段定义课程名称</div>',
        '<div style="color:blue;">表格内容错误</div>',
        '<div style="color:blue;">数据缺失</div>',
        '<div style="color:blue;">未填写学号，已导入但请注意排除学生同名的可能</div>',
        '<div style="color:blue;">新建的学时数据统计：</div>',
        '<div style="color:blue;">更新的学时数据统计：</div>'
    ]


    if info_show['person not found']:
        display_message += print_show[0]
        for person in info_show['person not found']:
            display_message += '未查询到 ' + person[0] + '<br>' + print_show[1]
            if person[1].exists():
                for message in person[1]:
                    display_message += '<div style="color:cadetblue;">' + message.name + ' ' + message.person_id.username + '</div>'
            if person[2] != None and person[2].exists():
                for message in person[2]:
                    display_message += '<div style="color:cadetblue;">' + message.name + ' ' + message.person_id.username + '</div>'
            elif not person[1].exists():
                display_message += '<div style="color:cadetblue;">未查询到类似数据</div>'
            display_message += '<br>'

    if info_show['course not found']:
        display_message += print_show[2]
        for course in info_show['course not found']:
            display_message += '<div style="color:rgb(86, 170, 142);">' + course + '</div>'

    if info_show['type error']:
        display_message += print_show[3]
        for error in info_show['type error']:
            display_message += '<div style="color:rgb(86, 170, 142);">' + '表格内容: ' + error + '</div>'

    if info_show['data miss']:
        display_message += print_show[4]
        for error in info_show['data miss']:
            display_message += '<div style="color:rgb(86, 170, 142);">' + '表格内容: ' + error + '</div>'

    if info_show['stuID miss']:
        display_message += print_show[5]
        for stu in info_show['stuID miss']:
            display_message += '<div style="color:rgb(86, 170, 142);">' + '表格内容: ' + stu + '</div>'

    context = dict(message=display_message)
    return render(request, "debugging.html", context)


def load_org_tag(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    try:
        org_tag_def = load_file("orgtag.csv")
    except:
        context = {"message": "没有找到orgtag.csv,请确认该文件已经在test_data中。"}
        return render(request, "debugging.html", context)
    tag_list = []
    for _, tag_dict in org_tag_def.iterrows():
        tag_name = tag_dict["name"]
        tag_color = tag_dict["color"]
        tag_list.append(
            OrganizationTag(
                name=tag_name,
                color=tag_color,
            )
        )
    OrganizationTag.objects.bulk_create(tag_list)
    context = {"message": "导入组织标签类型信息成功！"}
    return render(request, "debugging.html", context)


def load_tags_for_old_org(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)
    try:
        org_tag_def = load_file("oldorgtags.csv")
    except:
        context = {"message": "没有找到oldorgtags.csv,请确认该文件已经在test_data中。"}
        return render(request, "debugging.html", context)
    error_dict = {}
    org_num = 0
    for _, tag_dict in org_tag_def.iterrows():
        org_num += 1
        err = False
        with transaction.atomic():
            try:
                useroj = Organization.objects.select_for_update().get(oname=tag_dict[0])
                for tag in tag_dict[1:]:
                    useroj.tags.add(OrganizationTag.objects.get(name=tag))
            except Exception as e:
                if not(type(tag)==float and math.isnan(tag)): # 说明不是因遍历至空单元格导致的异常
                    error_dict[tag_dict[0]] = e
                    err = True
            if not err:  # 只有未出现异常，组织的标签信息才被保存
                useroj.save()
    context = {
        "message": '<br/>'.join((
                    f"共尝试导入{org_num}个组织的标签信息",
                    f"导入成功的组织：{org_num - len(error_dict)}个",
                    f"导入失败的组织：{len(error_dict)}个",
                    f'错误原因：' if error_dict else ''
                    ) + tuple(f'{org}：{err}' for org, err in error_dict.items())
                    )
        }
    return render(request, "debugging.html", context)


def load_feedback():
    '''该函数用于导入反馈详情的数据(csv)'''
    try:
        feedback_df = load_file("feedbackinf.csv")
    except:
        return "没有找到feedbackinf.csv,请确认该文件已经在test_data中。"
    error_dict = {}
    feedback_num = 0
    for _, feedback_dict in feedback_df.iterrows():
        feedback_num += 1
        err = False
        try:
            type_id = FeedbackType.objects.get(name=feedback_dict["type"]).id
            person_id = NaturalPerson.objects.get(name=feedback_dict["person"]).id
            org_id = Organization.objects.get(oname=feedback_dict["org"]).id

            feedback, mid = Feedback.objects.get_or_create(
                type_id=type_id, person_id=person_id, org_id=org_id,
            )

            feedback.title = feedback_dict["title"]
            feedback.content = feedback_dict["content"]

            issue_status_dict = {"草稿": 0, "已发布": 1, "已删除": 2,}
            read_status_dict = {"已读": 0, "未读": 1,}
            solve_status_dict = {"已解决": 0, "解决中": 1, "无法解决": 2,}
            public_status_dict = {"公开": 0, "未公开": 1, "撤销公开": 2, "强制不公开": 3,}

            assert feedback_dict["issue_status"] in issue_status_dict.keys()
            feedback.issue_status = issue_status_dict[feedback_dict["issue_status"]]

            assert feedback_dict["read_status"] in read_status_dict.keys()
            feedback.read_status = read_status_dict[feedback_dict["read_status"]]

            assert feedback_dict["solve_status"] in solve_status_dict.keys()
            feedback.solve_status = solve_status_dict[feedback_dict["solve_status"]]

            assert feedback_dict["public_status"] in public_status_dict.keys()
            feedback.public_status = public_status_dict[feedback_dict["public_status"]]

            if feedback_dict["publisher_public"].lower() == "true":
                feedback.publisher_public = True
            else:
                feedback.publisher_public = False

            if feedback_dict["org_public"].lower() == "true":
                feedback.org_public = True
            else:
                feedback.org_public = False

        except Exception as e:
            err = True
            error_dict["{}: {}".format(feedback_num, feedback_dict["title"])] = '''
                填写状态信息有误，请再次检查发布/阅读/解决/公开状态(文字)是否填写正确！
            ''' if isinstance(e,AssertionError) else e
            feedback.delete()

        if not err:
            feedback.save()

    return '<br/>'.join((
                    f"共尝试导入{feedback_num}条反馈的详细信息",
                    f"导入成功的反馈：{feedback_num - len(error_dict)}条",
                    f"导入失败的反馈：{len(error_dict)}条",
                    f'错误原因：' if error_dict else ''
                    ) + tuple(f'{fb}：{err}' for fb, err in error_dict.items()
                    ) + ('',
                    f"请注意：下面的字段必须填写对应的选项，否则反馈信息将无法保存！",
                    f"（1）issue_status：草稿 / 已发布 / 已删除",
                    f"（2）read_status：已读 / 未读",
                    f"（3）solve_status：已解决 / 解决中 / 无法解决",
                    f"（4）public_status：公开 / 未公开 / 撤销公开 / 强制不公开"
                    ))


def load_feedback_type():
    '''该函数用于导入反馈类型的数据(csv)'''
    try:
        feedback_type_df = load_file("feedbacktype.csv")
    except:
        return "没有找到feedbacktype.csv,请确认该文件已经在test_data中。"
    type_list = []
    for _, type_dict in feedback_type_df.iterrows():
        type_id = int(type_dict["id"])
        type_name = type_dict["name"]
        flexible = int(type_dict["flexible"])
        if flexible == 0:
            feedbacktype, mid = FeedbackType.objects.get_or_create(id=type_id)
        elif flexible == 1:
            otype = type_dict["org_type"]
            otype_id = OrganizationType.objects.get(otype_name=otype).otype_id
            feedbacktype, mid = FeedbackType.objects.get_or_create(
                id=type_id, org_type_id=otype_id,
            )
        else:
            otype = type_dict["org_type"]
            org = type_dict["org"]
            otype_id = OrganizationType.objects.get(otype_name=otype).otype_id
            org_id = Organization.objects.get(oname=org).id
            feedbacktype, mid = FeedbackType.objects.get_or_create(
                id=type_id, org_type_id=otype_id, org_id=org_id,
            )
        feedbacktype.name = type_name
        feedbacktype.flexible = flexible
        feedbacktype.save()

    FeedbackType.objects.bulk_create(type_list)
    return "导入反馈类型信息成功！"


def load_feedback_comments():
    '''该函数用于导入反馈的评论(feedbackcomments.csv)
    需要先导入feedbackinf.csv'''
    try:
        feedback_df = load_file("feedbackcomments.csv")
    except:
        return "没有找到feedbackcomments.csv,请确认该文件已经在test_data中。"
    error_dict = {}
    comment_num = 0
    for _, comment_dict in feedback_df.iterrows():
        comment_num += 1
        err = False
        try:
            feedback = Feedback.objects.get(id=comment_dict["fid"])
            commentator, commentator_type = get_user_by_name(comment_dict["commentator"])
            comment_time = datetime.strptime(comment_dict["time"], "%m/%d/%Y %H:%M %p")

            comment = Comment.objects.create(
                commentbase=feedback, commentator=commentator, text=comment_dict["text"], time=comment_time
            )

        except Exception as e:
            err = True
            error_dict["{}: {}".format(comment_num, comment_dict["fid"])] = '''
                填写状态信息有误，请再次检查发布/阅读/解决/公开状态(文字)是否填写正确！
            ''' if isinstance(e,AssertionError) else e
            comment.delete()

        if not err:
            comment.save()

    return '<br/>'.join((
                    f"共尝试导入{comment}条反馈评论",
                    f"导入成功的反馈：{comment_num - len(error_dict)}条",
                    f"导入失败的反馈：{len(error_dict)}条",
                    f'错误原因：' if error_dict else ''
                    ) + tuple(f'{fb}：{err}' for fb, err in error_dict.items()
                    ))


def load_feedback_data(request):
    if request.user.is_superuser:
        load_type = request.GET.get("loadtype", None)
        message = "加载失败！"
        if load_type is None:
            message = "没有传入loadtype参数:[detail,type或comment]"
        elif load_type == "type":
            message = load_feedback_type()
        elif load_type == "detail":
            message = load_feedback()
        elif load_type == "comment":
            message = load_feedback_comments()
        else:
            message = "没有得到loadtype参数:[detail或otype]"
    else:
        message = "请先以超级账户登录后台后再操作！"
    return render(request, "debugging.html", locals())
