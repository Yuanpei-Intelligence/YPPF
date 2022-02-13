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
    Semester
)
from app.utils import random_code_init

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


def load_file(file):
    return pd.read_csv(f"test_data/{file}", dtype=object, encoding="utf-8")


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
            username = org_dict["organization_id"]
            password = 'YPPFtest' if DEBUG else random_code_init(username)
            if username[:2] == "zz":
                oname = org_dict["oname"]
                type_id = org_dict["otype_id"]
                persons = org_dict.get("person", "待定")
                pos = max(0, int(org_dict.get("pos", 0)))
                user, mid = User.objects.get_or_create(username=username)
                user.set_password(password)
                user.save()
                orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
                org, mid = Organization.objects.get_or_create(
                    organization_id=user, otype=orgtype
                )
                org.oname = oname
                org.save()
                msg += '<br/>成功创建组织：'+oname

                for person in persons.split(','):
                    people = NaturalPerson.objects.get(name=person)
                    position, mid = Position.objects.get_or_create(
                        person=people, org=org, status=Position.Status.INSERVICE,
                        pos=pos, is_admin=True,
                    )
                    position.save()
                    msg += '<br/>&emsp;&emsp;成功增加负责人：'+person
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


def load_stu_data(request):
    if not request.user.is_superuser:
        context = {"message": "请先以超级账户登录后台后再操作！"}
        return render(request, "debugging.html", context)

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
                # continue
            # 这一步的PBKDF2加密算法太慢了
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
    return render(request, "debugging.html", context)


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


def load_CouRecord(request):
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
    if semester in ['秋季', '秋']:
        semester = 'Fall'
    elif semester in ['春季', '春']:
        semester = 'Spring'

    course_type_all = {
       "德" : Course.CourseType.MORAL ,
       "智" : Course.CourseType.INTELLECTUAL , 
       "体" : Course.CourseType.PHYSICAL ,
       "美" : Course.CourseType.AESTHETICS,
       "劳" : Course.CourseType.LABOUR,
    }
    course_info = courserecord_file['info'] #info这个sheet
    info_height ,info_width = course_info.shape 
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
                    year = year,
                    semester = semester,
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
        height,width = course_df.shape
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

        if  course_get.exists():  #查找到了相应course
            course_found = True
        else:
            info_show["course not found"].append(course)

        for i in range(4,height): 
            #每个sheet开头有几行不是学时信息，所以跳过
            sid = course_df.iloc[i, 1]  #学号
            name = course_df.iloc[i, 2]
            times = course_df.iloc[i, 3]
            hours = course_df.iloc[i, 4]    
            record_view = str(course)+' '+str(sid)+' '+str(name)+' '+str(times)+' '+str(hours)
            if (type(name)!=str and sid is numpy.nan): continue  #允许中间有空行
            if (type(sid) not in [int,float] or type(times) not in [int,float] or type(hours) not in [int,float]):
                info_show["type error"].append(record_view)
                continue
            
            person = NaturalPerson.objects.filter( name=name )
            if (times is numpy.nan) or (hours is numpy.nan): #次数和学时缺少
                info_show["data miss"].append(record_view)
                continue
            elif sid is numpy.nan:   #没有学号
                info_show["stuID miss"].append(record_view)
            else:  #若有学号，则根据学号继续查找（排除重名）
                person = person.filter(person_id__username = str(int(sid)))

            if not person.exists():
                info_show["person not found"].append(
                    [str(course)+' '+str(sid)+' '+name+' '+str(times)+' '+str(hours), ])
                #若同时按照学号和姓名查找不到的话，则只用姓名或者只用学号查找可能的人员
                person_guess_byname = NaturalPerson.objects.filter(name = name ) 
                if sid is not numpy.nan: #若填了学号的话，则试着查找
                    person_guess_byId = NaturalPerson.objects.filter(person_id__username = str(int(sid)))
                else: person_guess_byId=None
                info_show["person not found"][-1]+=[person_guess_byname, person_guess_byId]    
                continue
            
            record = CourseRecord.objects.filter( #查询是否已经有记录
                person = person[0],
                year = year,
                semester = Semester.get(semester),
            )
            record_search_course = record.filter(course__name= course,)
            record_search_extra = record.filter(extra_name = course,)
            if (not record_search_course.exists()) and (not record_search_extra.exists()):
                newrecord = CourseRecord.objects.create(
                    person = person[0],
                    extra_name = course,
                    attend_times = times,
                    total_hours = hours,
                    year = year,
                    semester = Semester.get(semester),
                )
                if course_found: 
                    newrecord.course = course_get[0] 
                    newrecord.save()    

            elif record_search_course.exists():
                record_search_course.update(
                    attend_times = times, 
                    total_hours = hours
                )
            else:
                record_search_extra.update(
                    attend_times = times, 
                    total_hours = hours
                )
    # ----- 以下为前端展示导入的结果 ------
    context = {
        'message':u'导入完成\n',
    }
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

    
    if info_show['person not found'] != []:
        context['message'] += print_show[0]
        for person in info_show['person not found']:
            context['message']+= '未查询到 ' +person[0]+'<br>'+print_show[1]
            if person[1].exists():
                for message in person[1]:
                    context['message'] += '<div style="color:cadetblue;">'+message.name +' '+ message.person_id.username+'</div>'
            if person[2].exists():
                for message in person[2]:
                    context['message'] += '<div style="color:cadetblue;">'+message.name +' '+ message.person_id.username+'</div>'
            elif not person[1].exists():
                context['message'] += '<div style="color:cadetblue;">未查询到类似数据</div>'
            context['message'] += '<br>'

    if info_show['course not found'] != []:
        context['message'] += print_show[2]
        for course in info_show['course not found']:
            context['message']+= '<div style="color:rgb(86, 170, 142);">'+course+'</div>'

    if info_show['type error'] != []:
        context['message'] += print_show[3]
        for error in info_show['type error']:
            context['message']+= '<div style="color:rgb(86, 170, 142);">'+'表格内容: '+error+'</div>'

    if info_show['data miss'] != []:
        context['message'] += print_show[4]
        for error in info_show['data miss']:
            context['message']+= '<div style="color:rgb(86, 170, 142);">'+'表格内容: '+error+'</div>'

    if info_show['stuID miss'] != []:
        context['message'] += print_show[5]
        for stu in info_show['stuID miss']:
            context['message']+= '<div style="color:rgb(86, 170, 142);">'+'表格内容: '+stu+'</div>'

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
    context = {"message": "导入组织类型标签信息成功！"}
    return render(request, "debugging.html", context)
