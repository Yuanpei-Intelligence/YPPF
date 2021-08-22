from threading import local
from django.dispatch.dispatcher import NO_RECEIVERS, receiver
from django.template.defaulttags import register
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    OrganizationType,
    Position,
    Activity,
    TransferRecord,
    Participant,
    Notification,
    NewOrganization,
    Comment,
    CommentPhoto,
    YQPointDistribute,
    Reimbursement
)
from django.db.models import Max
import app.utils as utils
from app.forms import UserForm
from app.utils import url_check, check_cross_site
from app.wechat_send import publish_notification
from boottest import local_dict
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.contrib import auth, messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

import json
from time import mktime
from datetime import date, datetime, timedelta
from urllib import parse
import re
import random
import requests  # 发送验证码
import io
import csv
import qrcode

# 定时任务注册
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job
from .scheduler_func import scheduler

# 注册启动以上schedule任务
register_events(scheduler)
scheduler.start()

email_url = local_dict["url"]["email_url"]
hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])
email_coder = MySHA256Hasher(local_dict["hash"]["email"])


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


def index(request):
    arg_origin = request.GET.get("origin")
    modpw_status = request.GET.get("modinfo")
    # request.GET['success'] = "no"
    arg_islogout = request.GET.get("is_logout")
    alert = request.GET.get("alert")
    html_display = dict()
    if (
            request.method == "GET"
            and modpw_status is not None
            and modpw_status == "success"
    ):
        html_display["warn_code"] = 2
        html_display["warn_message"] = "修改密码成功!"
        auth.logout(request)
        return render(request, "index.html", locals())

    if alert is not None:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "检测到恶意 URL，请与系统管理员进行联系。"
        auth.logout(request)
        return render(request, "index.html", locals())

    if arg_islogout is not None:
        if request.user.is_authenticated:
            auth.logout(request)
            return render(request, "index.html", locals())
    if arg_origin is None:  # 非外部接入
        if request.user.is_authenticated:
            return redirect("/welcome/")
            """
            valid, user_type , html_display = utils.check_user_type(request.user)
            if not valid:
                return render(request, 'index.html', locals())
            return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
            """
    # 恶意的 origin
    if not url_check(arg_origin):
        return redirect("/index/?alert=1")

    if request.method == "POST" and request.POST:
        username = request.POST["username"]
        password = request.POST["password"]

        try:
            user = User.objects.filter(username=username)
            if len(user) == 0:
                org = Organization.objects.get(
                    oname=username)  # 如果get不到，就是账号不存在了
                user = org.organization_id
                username = user.username
            else:
                user = user[0]
        except:
            # if arg_origin is not None:
            #    redirect(f'/login/?origin={arg_origin}')
            html_display["warn_message"] = local_dict["msg"]["404"]
            html_display["warn_code"] = 1
            return render(request, "index.html", locals())
        userinfo = auth.authenticate(username=username, password=password)
        if userinfo:
            auth.login(request, userinfo)
            request.session["username"] = username
            if arg_origin is not None:

                if not check_cross_site(request, arg_origin):
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "当前账户不能进行地下室预约，请使用个人账户登录后预约"
                    return redirect("/welcome/?warn_code={}&warn_message={}".format(
                        html_display["warn_code"], html_display["warn_message"]))
                if not arg_origin.startswith('http'): # 非外部链接，合法性已经检查过
                    return redirect(arg_origin)       # 不需要加密验证
                d = datetime.utcnow()
                t = mktime(datetime.timetuple(d))
                timeStamp = str(int(t))
                en_pw = hash_coder.encode(username + timeStamp)
                try:
                    userinfo = NaturalPerson.objects.get(person_id=username)
                    name = userinfo.name
                    return redirect(
                        arg_origin
                        + f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}&name={name}"
                    )
                except:
                    return redirect(
                        arg_origin
                        + f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}"
                    )
            else:
                # 先处理初次登录
                valid, user_type, html_display = utils.check_user_type(
                    request.user)
                if not valid:
                    return redirect("/logout/")
                me = utils.get_person_or_org(userinfo, user_type)
                if me.first_time_login:
                    return redirect("/modpw/")

                return redirect("/welcome/")
                """
                valid, user_type , html_display = utils.check_user_type(request.user)
                if not valid:
                    return render(request, 'index.html', locals())
                return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
                """
        else:
            html_display["warn_code"] = 1
            html_display["warn_message"] = local_dict["msg"]["406"]

    # 非 post 过来的
    if arg_origin is not None:
        if request.user.is_authenticated:

            if not check_cross_site(request, arg_origin):
                html_display = dict()
                html_display["warn_code"] = 1
                html_display["warn_message"] = "当前账户不能进行地下室预约，请使用个人账户登录后预约"
                return redirect("/welcome/?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]))

            d = datetime.utcnow()
            t = mktime(datetime.timetuple(d))
            timeStamp = str(int(t))
            print("utc time: ", d)
            print(timeStamp)
            username = request.session["username"]
            en_pw = hash_coder.encode(username + timeStamp)
            return redirect(
                arg_origin +
                f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}"
            )

    return render(request, "index.html", locals())


# Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5PasswordHasher("wechat_login")


def miniLogin(request):
    try:
        assert request.method == "POST"
        username = request.POST["username"]
        password = request.POST["password"]
        secret_token = request.POST["secret_token"]
        assert wechat_login_coder.verify(username, secret_token) == True
        user = User.objects.get(username=username)

        userinfo = auth.authenticate(username=username, password=password)

        if userinfo:

            auth.login(request, userinfo)

            request.session["username"] = username
            en_pw = hash_coder.encode(request.session["username"])
            user_account = NaturalPerson.objects.get(person_id=username)
            return JsonResponse({"Sname": user_account.name, "Succeed": 1}, status=200)
        else:
            return JsonResponse({"Sname": username, "Succeed": 0}, status=400)
    except:
        return JsonResponse({"Sname": "", "Succeed": 0}, status=400)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def stuinfo(request, name=None):
    """
        进入到这里的逻辑:
        首先必须登录，并且不是超级账户
        如果name是空
            如果是个人账户，那么就自动跳转个人主页"/stuinfo/myname"
            如果是组织账户，那么自动跳转welcome
        如果name非空但是找不到对应的对象
            自动跳转到welcome
        如果name有明确的对象
            如果不重名
                如果是自己，那么呈现并且有左边栏
                如果不是自己或者自己是组织，那么呈现并且没有侧边栏
            如果重名
                那么期望有一个"+"在name中，如果搜不到就跳转到Search/?Query=name让他跳转去
    """

    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)
    

    oneself = utils.get_person_or_org(user, user_type)

    if name is None:
        if user_type == "Organization":
            return redirect("/welcome/")  # 组织只能指定学生姓名访问
        else:  # 跳轉到自己的頁面
            assert user_type == "Person"
            full_path = request.get_full_path()

            append_url = "" if (
                    "?" not in full_path) else "?" + full_path.split("?")[1]
            return redirect("/stuinfo/" + oneself.name + append_url)
    else:
        # 先对可能的加号做处理
        name_list = name.split("+")
        name = name_list[0]
        person = NaturalPerson.objects.activated().filter(name=name)
        if len(person) == 0:  # 查无此人
            return redirect("/welcome/")
        if len(person) == 1:  # 无重名
            person = person[0]
        else:  # 有很多人，这时候假设加号后面的是user的id
            if len(name_list) == 1:  # 没有任何后缀信息，那么如果是自己则跳转主页，否则跳转搜索
                if user_type == "Person" and oneself.name == name:
                    person = oneself
                else:  # 不是自己，信息不全跳转搜索
                    return redirect("/search?Query=" + name)
            else:
                obtain_id = int(name_list[1])  # 获取增补信息
                get_user = User.objects.get(id=obtain_id)
                potential_person = NaturalPerson.objects.activated().get(
                    person_id=get_user
                )
                assert potential_person in person
                person = potential_person

        is_myself = user_type == "Person" and person.person_id == user  # 用一个字段储存是否是自己
        html_display["is_myself"] = is_myself  # 存入显示

        # 制作属于组织的卡片（头像，名称（+链接），介绍，职位）
        person_pos_infos = Position.objects.activated().filter(
            Q(person=person) & Q(show_post=True)
        )
        oneself_org_ids = [oneself] if user_type == 'Organization' else Position.objects.activated().filter(
            Q(person=oneself) & Q(show_post=True)).values("org")
        org_is_same = [
            id in oneself_org_ids for id in person_pos_infos.values("org")]
        join_org_info = Organization.objects.filter(
            id__in=person_pos_infos.values("org")
        )  # ta属于的组织
        org_avas = [utils.get_user_ava(org, "organization")
                    for org in join_org_info]
        org_poss = person_pos_infos.values("pos")
        org_statuss = person_pos_infos.values("status")
        html_display["org_info"] = list(
            zip(join_org_info, org_avas, org_poss, org_statuss, org_is_same)
        )
        html_display["org_len"] = len(html_display["org_info"])

        # for activity in Activity.objects.all():
        #     print(activity)
        #     Participant.objects.create(activity_id=activity, person_id=person)

        # 制作参与活动的卡片（时间，名称（+链接），组织，地点，介绍，状态）
        participants = Participant.objects.filter(person_id=person.id)
        activities = Activity.objects.filter(
            id__in=participants.values('activity_id'))
        if user_type == 'Person':
            activities_me = Participant.objects.filter(
                person_id=person.id).values('activity_id')
            activity_is_same = [
                activity in activities_me
                for activity in participants.values("activity_id")
            ]
        else:
            activities_me = activities.filter(
                organization_id=oneself.id).values('id')
            activities_me = [activity['id'] for activity in activities_me]
            activity_is_same = [
                activity['activity_id'] in activities_me
                for activity in participants.values("activity_id")
            ]
        participate_status_list = participants.values('status')
        participate_status_list = [info['status']
                                   for info in participate_status_list]
        status_color = {
            Activity.Status.REVIEWING: "primary",
            Activity.Status.CANCELED: "secondary",
            Activity.Status.APPLYING: "info",
            Activity.Status.WAITING: "warning",
            Activity.Status.PROGRESSING: "success",
            Activity.Status.END: "danger",
            Participant.AttendStatus.APPLYING: "primary",
            Participant.AttendStatus.APLLYFAILED: "danger",
            Participant.AttendStatus.APLLYSUCCESS: "info",
            Participant.AttendStatus.ATTENDED: "success",
            Participant.AttendStatus.UNATTENDED: "warning",
            Participant.AttendStatus.CANCELED: "secondary",
        }
        activity_color_list = [status_color[activity.status]
                               for activity in activities]
        attend_color_list = [status_color[status]
                             for status in participate_status_list]
        activity_info = list(
            zip(
                activities,
                participate_status_list,
                activity_is_same,
                activity_color_list,
                attend_color_list,
            )
        )
        activity_info.sort(key=lambda a: a[0].start, reverse=True)
        html_display["activity_info"] = activity_info
        html_display["activity_len"] = len(html_display["activity_info"])

        # 警告呈现信息

        try:
            html_display["warn_code"] = int(
                request.GET.get("warn_code", 0)
            )  # 是否有来自外部的消息
        except:
            return redirect("/welcome/")
        html_display["warn_message"] = request.GET.get(
            "warn_message", "")  # 提醒的具体内容

        modpw_status = request.GET.get("modinfo", None)
        if modpw_status is not None and modpw_status == "success":
            html_display["warn_code"] = 2
            html_display["warn_message"] = "修改个人信息成功!"

        # 存储被查询人的信息
        context = dict()

        context["person"] = person

        def gender2title(g):
            return "他" if g == 0 else "她"

        context["title"] = (
            "我"
            if is_myself
            else gender2title(person.gender)
            if person.show_gender
            else "ta"
        )


        context["avatar_path"] = utils.get_user_ava(person, "Person")
        context["wallpaper_path"] = utils.get_user_wallpaper(person)

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display
        bar_display = utils.get_sidebar_and_navbar(request.user)
        bar_display["title_name"] = "个人主页"
        bar_display["navbar_name"] = "个人主页"
        bar_display["help_message"] = local_dict["help_message"]["个人主页"]
        origin = request.get_full_path()

        return render(request, "stuinfo.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def request_login_org(request, name=None):  # 特指个人希望通过个人账户登入组织账户的逻辑
    """
        这个函数的逻辑是，个人账户点击左侧的管理组织直接跳转登录到组织账户
        首先检查登录的user是个人账户，否则直接跳转orginfo
        如果个人账户对应的是name对应的组织的最高权限人，那么允许登录，否则跳转回stuinfo并warning
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    if user_type == "Organization":
        return redirect("/orginfo/")
    try:
        me = NaturalPerson.objects.activated().get(person_id=user)
    except:  # 找不到合法的用户
        return redirect("/welcome/")
    if name is None:  # 个人登录未指定登入组织,属于不合法行为,弹回欢迎
        return redirect("/welcome/")
    else:  # 确认有无这个组织
        try:
            org = Organization.objects.get(oname=name)
        except:  # 找不到对应组织
            urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=找不到对应组织,请联系管理员!"
            return redirect(urls)
        try:
            position = Position.objects.activated().filter(org=org, person=me)
            assert len(position) == 1
            position = position[0]
            assert position.pos == 0
        except:
            urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=没有登录到该组织账户的权限!"
            return redirect(urls)
        # 到这里,是本人组织并且有权限登录
        auth.logout(request)
        auth.login(request, org.organization_id)  # 切换到组织账号
        if org.first_time_login:
            return redirect("/modpw/")
        return redirect("/orginfo/")


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def orginfo(request, name=None):
    """
        orginfo负责呈现组织主页，逻辑和stuinfo是一样的，可以参考
        只区分自然人和法人，不区分自然人里的负责人和非负责人。任何自然人看这个组织界面都是【不可管理/编辑组织信息】
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    me = utils.get_person_or_org(user, user_type)

    if name is None:  # 此时登陆的必需是法人账号，如果是自然人，则跳转welcome
        if user_type == "Person":
            return redirect("/welcome/")
        try:
            org = Organization.objects.activated().get(organization_id=user)
        except:
            return redirect("/welcome/")

        full_path = request.get_full_path()
        append_url = "" if (
            "?" not in full_path) else "?" + full_path.split("?")[1]
            
        return redirect("/orginfo/" + org.oname + append_url)

    try:  # 指定名字访问组织账号的，可以是自然人也可以是法人。在html里要注意区分！

        # 下面是组织信息

        org = Organization.objects.activated().get(oname=name)

    except:
        return redirect("/welcome/")

    organization_name = name
    organization_type_name = org.otype.otype_name
    org_avatar_path = utils.get_user_ava(org, "Organization")
    # org的属性 YQPoint 和 information 不在此赘述，直接在前端调用

    # 该学年、该学期、该组织的 活动的信息,分为 未结束continuing 和 已结束ended ，按时间顺序降序展现
    continuing_activity_list = (
        Activity.objects.activated()
        .filter(organization_id=org)
        .filter(
            status__in=[
                Activity.Status.REVIEWING,
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING,
            ]
        )
            .order_by("-start")
    )

    ended_activity_list = (
        Activity.objects.activated()
            .filter(organization_id=org)
            .filter(status__in=[Activity.Status.CANCELED, Activity.Status.END])
            .order_by("-start")
    )

    # 如果是用户登陆的话，就记录一下用户有没有加入该活动，用字典存每个活动的状态，再把字典存在列表里

    prepare_times = Activity.EndBeforeHours.prepare_times

    continuing_activity_list_participantrec = []

    for act in continuing_activity_list:
        dictmp = {}
        dictmp["act"] = act
        dictmp["endbefore"] = act.start - \
                              timedelta(hours=prepare_times[act.endbefore])
        if user_type == "Person":

            existlist = Participant.objects.filter(activity_id_id=act.id).filter(
                person_id_id=me.id
            )

            if existlist:  # 判断是否非空
                dictmp["status"] = existlist[0].status
            else:
                dictmp["status"] = "无记录"
        continuing_activity_list_participantrec.append(dictmp)

    ended_activity_list_participantrec = []
    for act in ended_activity_list:
        dictmp = {}
        dictmp["act"] = act
        dictmp["endbefore"] = act.start - \
                              timedelta(hours=prepare_times[act.endbefore])
        if user_type == "Person":
            existlist = Participant.objects.filter(activity_id_id=act.id).filter(
                person_id_id=me.id
            )
            if existlist:  # 判断是否非空
                dictmp["status"] = existlist[0].status
            else:
                dictmp["status"] = "无记录"
        ended_activity_list_participantrec.append(dictmp)

    # 判断我是不是老大, 首先设置为false, 然后如果有person_id和user一样, 就为True
    html_display["isboss"] = False

    # 组织成员list
    positions = Position.objects.activated().filter(org=org).order_by("pos")  # 升序
    member_list = []
    for p in positions:
        if p.person.person_id == user and p.pos == 0:
            html_display["isboss"] = True
        if p.show_post == True or p.pos == 0:
            member = {}
            member["person"] = p.person
            member["job"] = org.otype.get_name(p.pos)
            member["highest"] = True if p.pos == 0 else False

            member["avatar_path"] = utils.get_user_ava(
                member["person"], "Person")

            member_list.append(member)

    try:
        html_display["warn_code"] = int(
            request.GET.get("warn_code", 0))  # 是否有来自外部的消息
    except:
        return redirect("/welcome/")
    html_display["warn_message"] = request.GET.get(
        "warn_message", "")  # 提醒的具体内容

    modpw_status = request.GET.get("modinfo", None)
    if modpw_status is not None and modpw_status == "success":
        html_display["warn_code"] = 2
        html_display["warn_message"] = "修改组织信息成功!"

    # 补充左边栏信息

    # 判断是否为组织账户本身在登录
    html_display["is_myself"] = me == org

    # 再处理修改信息的回弹
    modpw_status = request.GET.get("modinfo", None)
    html_display["modpw_code"] = modpw_status is not None and modpw_status == "success"


    # 组织活动的信息

    # 补充一些呈现信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "组织主页"
    bar_display["navbar_name"] = "组织主页"

    # 转账后跳转
    origin = request.get_full_path()

    # 补充订阅该组织的按钮
    show_subscribe = False
    if user_type == "Person":
        show_subscribe = True
        subscribe_flag = True  # 默认在订阅列表中

        if organization_name in me.unsubscribe_list.values_list("oname", flat=True):
            subscribe_flag = False

    return render(request, "orginfo.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def homepage(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_person = True if user_type == "Person" else False
    me = utils.get_person_or_org(request.user, user_type)
    myname = me.name if is_person else me.oname

    # 直接储存在html_display中
    # profile_name = "个人主页" if is_person else "组织主页"
    # profile_url = "/stuinfo/" + myname if is_person else "/orginfo/" + myname

    html_display["is_myself"] = True

    try:
        html_display["warn_code"] = int(
            request.GET.get("warn_code", 0))  # 是否有来自外部的消息
    except:
        return redirect("/welcome/")
    html_display["warn_message"] = request.GET.get(
        "warn_message", "")  # 提醒的具体内容

    # 今天开始进行的活动,且不展示结束的活动。按开始时间由近到远排序
    nowtime = datetime.now()
    today_activity_list = (
        Activity.objects.activated()
        .filter(Q( start__year=nowtime.year) & Q( start__month=nowtime.month) & Q( start__day=nowtime.day))
        .filter(
            status__in=[
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING
            ]
        )
        .order_by("start")
    )
    # 今天可以报名的活动。按截止时间由近到远排序
    prepare_times = Activity.EndBeforeHours.prepare_times
    signup_rec = (
        Activity.objects.activated()
        .filter(status = Activity.Status.APPLYING)
    )
    today_signup_list = []
    for act in signup_rec:
        dictmp = {}
        dictmp["endbefore"] = act.start - timedelta(hours=prepare_times[act.endbefore])
        dictmp["act"] = act
        today_signup_list.append(dictmp)
    today_signup_list.sort(key=lambda x:x["endbefore"])


    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Welcome Page"
    bar_display["navbar_name"] = "近期要闻"


    return render(request, "welcome_page.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def account_setting(request):
    valid, user_type, html_display = utils.check_user_type(request.user)

    
    # 在这个页面 默认回归为自己的左边栏
    html_display["is_myself"] = True
    user = request.user
    me = utils.get_person_or_org(user, user_type)
    former_img = utils.get_user_ava(me, user_type)


    if user_type == "Person":
        info = NaturalPerson.objects.filter(person_id=user)
        userinfo = info.values()[0]

        useroj = NaturalPerson.objects.get(person_id=user)

        # print(json.loads(request.body.decode("utf-8")))
        if request.method == "POST" and request.POST:

            attr_dict = dict()

            attr_dict['nickname'] = request.POST['nickname']
            attr_dict['biography'] = request.POST["aboutBio"]
            attr_dict['telephone'] = request.POST["tel"]
            attr_dict['email'] = request.POST["email"]
            attr_dict['stu_major'] = request.POST["major"]
            attr_dict['stu_grade'] = request.POST['grade']
            attr_dict['stu_class'] = request.POST['class']
            attr_dict['stu_dorm'] = request.POST['dorm']

            ava = request.FILES.get("avatar")
            gender = request.POST['gender']

            show_dict = dict()

            show_dict['show_nickname'] = request.POST.get('show_nickname') == 'on'
            show_dict['show_gender'] = request.POST.get('show_gender') == 'on'
            show_dict['show_tel'] = request.POST.get('show_tel') == 'on'
            show_dict['show_email'] = request.POST.get('show_email') == 'on'
            show_dict['show_major'] = request.POST.get('show_major') == 'on'
            show_dict['show_grade'] = request.POST.get('show_grade') == 'on'
            show_dict['show_dorm'] = request.POST.get('show_dorm') == 'on'

            expr = bool(ava or (gender != useroj.get_gender_display()))
            expr += sum(
                [(getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "") for attr in attr_dict.keys()])
            expr += sum([getattr(useroj, show_attr) != show_dict[show_attr] for show_attr in show_dict.keys()])

            if gender != useroj.gender:
                useroj.gender = NaturalPerson.Gender.MALE if gender == '男' else NaturalPerson.Gender.FEMALE
            for attr in attr_dict.keys():
                if getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "":
                    setattr(useroj, attr, attr_dict[attr])
            for show_attr in show_dict.keys():
                if getattr(useroj, show_attr) != show_dict[show_attr]:
                    setattr(useroj, show_attr, show_dict[show_attr])
            if ava is None:
                pass
            else:
                useroj.avatar = ava
            useroj.save()
            avatar_path = settings.MEDIA_URL + str(ava)
            if expr == True:
                upload_state = True
                return redirect("/stuinfo/?modinfo=success")
            # else: 没有更新 从下面统一返回
    else:
        info = Organization.objects.filter(organization_id=user)
        userinfo = info.values()[0]

        useroj = Organization.objects.get(organization_id=user)


        if request.method == "POST" and request.POST:

            attr_dict = dict()
            attr_dict['introduction'] = request.POST['introduction']

            ava = request.FILES.get("avatar")

            expr = bool(ava)
            expr += sum(
                [(getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "") for attr in attr_dict.keys()])

            for attr in attr_dict.keys():
                if getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "":
                    setattr(useroj, attr, attr_dict[attr])
            if ava is None:
                pass
            else:
                useroj.avatar = ava
            useroj.save()
            avatar_path = settings.MEDIA_URL + str(ava)
            if expr == True:
                upload_state = True
                return redirect("/orginfo/?modinfo=success")
            # else: 没有修改信息 统一从下面返回

    # 补充网页呈现所需信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Account Setting"
    bar_display["navbar_name"] = "账户设置"
    bar_display["help_message"] = local_dict["help_message"]["账户设置"]

    if user_type == "Person":
        return render(request, "person_account_setting.html", locals())
    else:
        return render(request, "org_account_setting.html", locals())


def register(request):
    if request.user.is_superuser:
        if request.method == "POST" and request.POST:
            name = request.POST["name"]
            password = request.POST["password"]
            sno = request.POST["snum"]
            email = request.POST["email"]
            password2 = request.POST["password2"]
            stu_grade = request.POST["syear"]
            # gender = request.POST['sgender']
            if password != password2:
                render(request, "index.html")
            else:
                # user with same sno
                same_user = NaturalPerson.objects.filter(person_id=sno)
                if same_user:
                    render(request, "auth_register_boxed.html")
                same_email = NaturalPerson.objects.filter(email=email)
                if same_email:
                    render(request, "auth_register_boxed.html")

                # OK!
                user = User.objects.create(username=sno)
                user.set_password(password)
                user.save()

                new_user = NaturalPerson.objects.create(person_id=user)
                new_user.name = name
                new_user.email = email
                new_user.stu_grade = stu_grade
                new_user.save()
                return HttpResponseRedirect("/index/")
        return render(request, "auth_register_boxed.html")
    else:
        return HttpResponseRedirect("/index/")


# @login_required(redirect_field_name=None)
def logout(request):
    auth.logout(request)
    return HttpResponseRedirect("/index/")


"""
def org_spec(request, *args, **kwargs):
    arg = args[0]
    org_dict = local_dict['org']
    topic = org_dict[arg]
    org = Organization.objects.filter(oname=topic)
    pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
    try:
        pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
        boss_no = pos.values()[0]['person_id']#存疑，可能还有bug here
        boss = NaturalPerson.objects.get(person_id=boss_no).name
        job = pos.values()[0]['pos']
    except:
        person_incharge = '负责人'
    return render(request, 'org_spec.html', locals())
"""


def get_stu_img(request):
    print("in get stu img")
    stuId = request.GET.get("stuId")
    if stuId is not None:
        try:
            stu = NaturalPerson.objects.get(person_id=stuId)
            img_path = utils.get_user_ava(stu, "Person")
            return JsonResponse({"path": img_path}, status=200)
        except:
            return JsonResponse({"message": "Image not found!"}, status=404)
    return JsonResponse({"message": "User not found!"}, status=404)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def search(request):
    """
        搜索界面的呈现逻辑
        分成搜索个人和搜索组织两个模块，每个模块的呈现独立开，有内容才呈现，否则不显示
        搜索个人：
            支持使用姓名搜索，支持对未设为不可见的昵称和专业搜索
            搜索结果的呈现采用内容/未公开表示，所有列表为people_filed
        搜索组织
            支持使用组织名、组织类型搜索、一级负责人姓名
            组织的呈现内容由拓展表体现，不在这个界面呈现具体成员
            add by syb:
            支持通过组织名、组织类型来搜索组织
            支持通过公开关系的个人搜索组织，即如果某自然人用户可以被上面的人员搜索检出，
            而且该用户选择公开其与组织的关系，那么该组织将在搜索界面呈现。
            搜索结果的呈现内容见organization_field
        搜索活动
            支持通过活动名、组织来搜索活动。只要可以搜索到组织，组织对应的活动就也可以被搜到
            搜索结果的呈现见activity_field
    """

    valid, user_type, html_display = utils.check_user_type(request.user)


    query = request.GET.get("Query", "")
    if query == "":
        return redirect("/welcome/")

    not_found_message = "找不到符合搜索的信息或相关内容未公开！"
    # 首先搜索个人, 允许搜索姓名或者公开的专业, 删去小名搜索
    people_list = NaturalPerson.objects.filter(

        Q(name__icontains=query)
        | (  # (Q(nickname__icontains=query) & Q(show_nickname=True)) |
                Q(stu_major__icontains=query) & Q(show_major=True)
        )
    )

    # 接下来准备呈现的内容
    # 首先是准备搜索个人信息的部分
    people_field = [
        "姓名",
        "年级",
        "班级",
        # "昵称",
        # "性别",
        "专业",
        # "邮箱",
        # "电话",
        # "宿舍",
        "状态",
    ]  # 感觉将年级和班级分开呈现会简洁很多

    # 搜索组织
    # 先查找query作为姓名包含在字段中的职务信息, 选的是post为true或者职务等级为0
    pos_list = Position.objects.activated().filter(
        Q(person__name__icontains=query) & (Q(show_post=True) | Q(pos=0))
    )
    # 通过组织名、组织类名、和上述的职务信息对应的组织信息
    organization_list = Organization.objects.filter(
        Q(oname__icontains=query)
        | Q(otype__otype_name__icontains=query)
        | Q(id__in=pos_list.values("org"))
    ).prefetch_related("position_set")

    org_display_list = []
    for org in organization_list:
        org_display_list.append(
            {
                "oname": org.oname,
                "otype": org.otype,
                "pos0": [
                    w["person__name"]
                    for w in list(
                        org.position_set.activated()
                            .filter(pos=0)
                            .values("person__name")
                    )
                ],
            }
        )

    # 组织要呈现的具体内容
    organization_field = ["组织名称", "组织类型", "负责人", "近期活动"]

    # 搜索活动
    activity_list = Activity.objects.filter(
        Q(title__icontains=query) | Q(organization_id__oname__icontains=query)
    )

    # 活动要呈现的内容
    activity_field = ["活动名称", "承办组织", "状态"]

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Search"
    bar_display["navbar_name"] = "信息搜索"  #

    return render(request, "search.html", locals())


def test(request):
    request.session["cookies"] = "hello, i m still here."
    return render(request, "all_org.html")


def forget_password(request):
    """
        忘记密码页（Pylance可以提供文档字符串支持）
        页面效果
        -------
        - 根据（邮箱）验证码完成登录，提交后跳转到修改密码界面
        - 本质是登录而不是修改密码
        - 如果改成支持验证码登录只需修改页面和跳转（记得修改函数和页面名）
        页面逻辑
        -------
        1. 发送验证码
            1.5 验证码冷却避免多次发送
        2. 输入验证码
            2.5 保留表单信息
        3. 错误提醒和邮件发送提醒
        实现逻辑
        -------
        - 通过脚本使按钮提供不同的`send_captcha`值，区分按钮
        - 通过脚本实现验证码冷却，页面刷新后重置冷却（避免过长等待影响体验）
        - 通过`session`保证安全传输验证码和待验证用户
        - 成功发送/登录后才在`session`中记录信息
        - 页面模板中实现消息提醒
            - `err_code`非零值代表错误，在页面中显示
            - `err_code`=`0`或`4`是预设的提醒值，额外弹出提示框
            - forget_password.html中可以进一步修改
        - 尝试发送验证码后总是弹出提示框，通知用户验证码的发送情况
        注意事项
        -------
        - 尝试忘记密码的不一定是本人，一定要做好隐私和逻辑处理
            - 用户邮箱应当部分打码，避免向非本人提供隐私数据！
        - 不发送消息时`err_code`应为`None`或不声明，不同于modpw
        - `err_code`=`4`时弹出
        - 连接设置的timeout为6s
        - 如果引入企业微信验证，建议将send_captcha分为'qywx'和'email'
    """
    if request.session.get("received_user"):
        username = request.session["received_user"]  # 自动填充，方便跳转后继续
    if request.method == "POST":
        username = request.POST["username"]
        send_captcha = request.POST["send_captcha"] == "yes"
        vertify_code = request.POST["vertify_code"]  # 用户输入的验证码

        user = User.objects.filter(username=username)
        if not user:
            err_code = 1
            err_message = "账号不存在"
        elif len(user) != 1:
            err_code = 1
            err_message = "账号不唯一，请联系管理员"
        else:
            user = User.objects.get(username=username)
            try:
                useroj = NaturalPerson.objects.get(person_id=user)  # 目前只支持自然人
            except:
                err_code = 1
                err_message = "暂不支持组织账号忘记密码！"
                return render(request, "forget_password.html", locals())
            isFirst = useroj.first_time_login
            if isFirst:
                err_code = 2
                err_message = "初次登录密码与账号相同！"
            elif send_captcha:
                email = useroj.email
                if not email or email.lower() == "none" or "@" not in email:
                    err_code = 3
                    err_message = "您没有设置邮箱，请联系管理员" + \
                                  "或发送姓名、学号和常用邮箱至gypjwb@pku.edu.cn进行修改"  # TODO:记得填
                else:
                    # randint包含端点，randrange不包含
                    captcha = random.randrange(1000000)
                    captcha = f"{captcha:06}"
                    msg = (
                            f"<h3><b>亲爱的{useroj.name}同学：</b></h3><br/>"
                            "您好！您的账号正在进行邮箱验证，本次请求的验证码为：<br/>"
                            f'<p style="color:orange">{captcha}'
                            '<span style="color:gray">(仅'
                            f'<a href="{request.build_absolute_uri()}">当前页面</a>'
                            '有效)</span></p>'
                            f'点击进入<a href="{request.build_absolute_uri("/")}">元培成长档案</a><br/>'
                            "<br/>"
                            "元培学院开发组<br/>" + datetime.now().strftime("%Y年%m月%d日")
                    )
                    post_data = {
                        "sender": "元培学院开发组",  # 发件人标识
                        "toaddrs": [email],  # 收件人列表
                        "subject": "YPPF登录验证",  # 邮件主题/标题
                        "content": msg,  # 邮件内容
                        # 若subject为空, 第一个\n视为标题和内容的分隔符
                        "html": True,  # 可选 如果为真则content被解读为html
                        "private_level": 0,  # 可选 应在0-2之间
                        # 影响显示的收件人信息
                        # 0级全部显示, 1级只显示第一个收件人, 2级只显示发件人
                        "secret": email_coder.encode(msg),  # content加密后的密文
                    }
                    post_data = json.dumps(post_data)
                    pre, suf = email.rsplit("@", 1)
                    if len(pre) > 5:
                        pre = pre[:2] + "*" * len(pre[2:-3]) + pre[-3:]
                    try:
                        response = requests.post(
                            email_url, post_data, timeout=6)
                        response = response.json()
                        if response["status"] != 200:
                            err_code = 4
                            err_message = f"未能向{pre}@{suf}发送邮件"
                            print("向邮箱api发送失败，原因：", response["data"]["errMsg"])
                        else:
                            # 记录验证码发给谁 不使用username防止被修改
                            request.session["received_user"] = username
                            request.session["captcha"] = captcha
                            err_code = 0
                            err_message = f"验证码已发送至{pre}@{suf}"
                    except:
                        err_code = 4
                        err_message = "邮件发送失败：超时"
            else:
                captcha = request.session.get("captcha", "")
                received_user = request.session.get("received_user", "")
                if len(captcha) != 6 or username != received_user:
                    err_code = 5
                    err_message = "请先发送验证码"
                elif vertify_code.upper() == captcha.upper():
                    auth.login(request, user)
                    request.session.pop("captcha")
                    request.session.pop("received_user")  # 成功登录后不再保留
                    request.session["username"] = username
                    request.session["forgetpw"] = "yes"
                    return redirect(reverse("modpw"))
                else:
                    err_code = 6
                    err_message = "验证码不正确"
    return render(request, "forget_password.html", locals())


@login_required(redirect_field_name="origin")
def modpw(request):
    '''
        可能在三种情况进入这个页面：首次登陆；忘记密码；或者常规的修改密码。
        在忘记密码时，可以允许不输入旧的密码
        在首次登陆时，现在写的也可以不输入旧的密码（我还没想好这样合不合适）
            以上两种情况都可以直接进行密码修改
        常规修改要审核旧的密码
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    if not valid:
        return redirect("/index/")
    me = utils.get_person_or_org(request.user, user_type)
    isFirst = me.first_time_login
    # 在其他界面，如果isFirst为真，会跳转到这个页面
    # 现在，请使用@utils.check_user_access(redirect_url)包装器完成用户检查

    html_display["is_myself"] = True
    

    err_code = 0
    err_message = None
    forgetpw = request.session.get("forgetpw", "") == "yes"  # added by pht
    user = request.user
    username = user.username

    
    if request.method == "POST" and request.POST:
        oldpassword = request.POST["pw"]
        newpw = request.POST["new"]
        strict_check = False

        if oldpassword == newpw and strict_check and not (forgetpw or isFirst):
            err_code = 1
            err_message = "新密码不能与原密码相同"
        elif newpw == username and strict_check:
            err_code = 2
            err_message = "新密码不能与学号相同"
        elif newpw != oldpassword and (forgetpw or isFirst):  # added by pht
            err_code = 5
            err_message = "两次输入的密码不匹配"
        else:
            # 在1、忘记密码 2、首次登录 3、验证旧密码正确 的前提下，可以修改
            if forgetpw or isFirst:
                userauth = True
            else:
                userauth = auth.authenticate(
                    username=username, password=oldpassword) # 验证旧密码是否正确
            if userauth: # 可以修改
                try:  # modified by pht: if检查是错误的，不存在时get会报错
                    user.set_password(newpw)
                    user.save()
                    me.first_time_login = False
                    me.save()

                    if forgetpw:
                        request.session.pop("forgetpw")  # 删除session记录

                    urls = reverse("index") + "?modinfo=success"
                    return redirect(urls)
                except:  # modified by pht: 之前使用的if检查是错误的
                    err_code = 3
                    err_message = "学号不存在"
            else:
                err_code = 4
                err_message = "原始密码不正确"
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    # 补充一些呈现信息
    bar_display["title_name"] = "Modify Password"
    bar_display["navbar_name"] = "修改密码"
    return render(request, "modpw.html", locals())


# 调用的时候最好用 try
# 调用者把 activity_id 作为参数传过来
def applyActivity(request, activity_id, willingness):
    context = dict()
    context["success"] = False
    CREATE = True
    with transaction.atomic():
        try:
            activity = Activity.objects.select_for_update().get(id=activity_id)
            payer = NaturalPerson.objects.select_for_update().get(
                person_id=request.user
            )
        except:
            context["msg"] = "未能找到活动"

            return context
        """
        assert len(activity) == 1
        assert len(payer) == 1
        activity = activity[0]
        payer = payer[0]
        """
        if activity.status != Activity.Status.APPLYING:
            context["msg"] = "活动未开放报名."
            return context

        try:
            participant = Participant.objects.select_for_update().get(
                activity_id=activity, person_id=payer
            )
            if (
                    participant.status == Participant.AttendStatus.APPLYING
                    or participant.status == Participant.AttendStatus.APLLYSUCCESS
            ):
                context["msg"] = "您已申请报名过该活动。"
                return context
            elif (
                    participant.status == Participant.AttendStatus.ATTENDED
                    or participant.status == Participant.AttendStatus.APPLYING.UNATTENDED
            ):
                context["msg"] = "活动已开始。"
                return context
            elif participant.status == Participant.AttendStatus.CANCELED:
                CREATE = False
        except:
            pass
        organization_id = activity.organization_id_id
        organization = Organization.objects.select_for_update().get(id=organization_id)
        """
        assert len(organization) == 1
        organization = organization[0]
        """

        if not activity.bidding:
            amount = float(activity.YQPoint)
            # transaction，直接减没事
            if activity.current_participants < activity.capacity:
                activity.current_participants += 1
            else:
                context["msg"] = "活动已报满，请稍后再试。"
                return context
        else:
            amount = float(willingness)
            try:
                assert activity.YQPoint <= amount <= activity.YQPoint * 3
            except:
                context["msg"] = "投点范围为基础值的 1-3 倍"
                return context
            # 依然增加，此时current_participants统计的是报名的人数，是可以比总人数多的
            activity.current_participants += 1

        try:
            assert amount == int(amount * 10) / 10
        except:
            context["msg"] = "精度最高为一位小数"
            return context

        if payer.YQPoint < amount:
            context["msg"] = "没有足够的元气值。"
            return context

        payer.YQPoint -= amount

        record = TransferRecord.objects.create(
            proposer=request.user, recipient=organization.organization_id
        )
        record.amount = amount
        record.message = f"Participate Activity {activity.title}"
        organization.YQPoint += float(amount)
        record.status = TransferRecord.TransferStatus.ACCEPTED

        record.time = str(datetime.now())
        record.corres_act = activity

        if CREATE:
            participant = Participant.objects.create(
                activity_id=activity, person_id=payer
            )
        if not activity.bidding:
            participant.status = Participant.AttendStatus.APLLYSUCCESS
        else:
            participant.status = Participant.AttendStatus.APPLYING

        participant.save()
        record.save()
        payer.save()
        activity.save()
        organization.save()

    context["pStatus"] = participant.status
    context["msg"] = "操作成功。"
    context["success"] = True
    return context


# 用已有的搜索，加一个转账的想他转账的 field
# 调用的时候传一下 url 到 origin
# 搜索不希望出现学号，rid 为 User 的 index
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def transaction_page(request, rid=None):
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 如果希望前移，请联系YHT
    bar_display = utils.get_sidebar_and_navbar(request.user)
    # 补充一些呈现信息
    bar_display["title_name"] = "Transaction"
    bar_display["navbar_name"] = "发起转账"

    context = dict()
    if request.method == "POST":
        # 如果是post方法，从数据中读取rid
        rid = request.POST.get("rid")  # index

    # 同样首先进行合法性检查
    try:
        user = User.objects.get(id=rid)
        recipient = utils.get_person_or_org(user)
    except:
        urls = "/welcome/" + "?warn_code=1&warn_message=遭遇非法收款人!如有问题, 请联系管理员!"
        return redirect(urls)

    # 不要转给自己
    if int(rid) == request.user.id:
        urls = "/welcome/" + "?warn_code=1&warn_message=遭遇非法收款人!如有问题, 请联系管理员!"
        return redirect(urls)

    # 获取名字
    _, _, context = utils.check_user_type(user)
    context = utils.get_sidebar_and_navbar(user,context)
    name = recipient.name if context["user_type"] == "Person" else recipient.oname
    context["name"] = name
    context["rid"] = rid
    context["YQPoint"] = me.YQPoint

    # 储存返回跳转的url
    if context["user_type"] == "Person":

        context["return_url"] = (
                context["profile_url"] + context["name"] + "+" + context["rid"]
        )
    else:
        context["return_url"] = context["profile_url"] + context["name"]

    # 如果是post, 说明发起了一起转账
    # 到这里, rid没有问题, 接收方和发起方都已经确定
    if request.method == "POST":
        # 获取转账消息, 如果没有消息, 则为空
        transaction_msg = request.POST.get("msg", "")

        # 检查发起转账的数据
        try:
            amount = float(request.POST.get("amount", None))
            assert amount is not None
            assert amount > 0
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "转账金额为空或为负数, 请填写合法的金额!"

            

            return render(request, "transaction_page.html", locals())

        if int(amount * 10) / 10 != amount:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "转账金额的最大精度为0.1, 请填写合法的金额!"

            

            return render(request, "transaction_page.html", locals())

        # 到这里, 参数的合法性检查完成了, 接下来应该是检查发起人的账户, 够钱就转
        try:
            with transaction.atomic():
                # 首先锁定用户
                if user_type == "Person":
                    payer = (
                        NaturalPerson.objects.activated()
                            .select_for_update()
                            .get(person_id=request.user)
                    )
                else:
                    payer = (
                        Organization.objects.activated()
                            .select_for_update()
                            .get(organization_id=request.user)
                    )

                # 接下来确定金额
                if payer.YQPoint < amount:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = (
                            "现存元气值余额为"
                            + str(payer.YQPoint)
                            + ", 不足以发起额度为"
                            + str(amount)
                            + "的转账!"
                    )
                else:
                    payer.YQPoint -= amount
                    record = TransferRecord.objects.create(
                        proposer=request.user,
                        recipient=user,
                        amount=amount,
                        message=transaction_msg,
                    )
                    record.save()
                    payer.save()
                    warn_message = "成功发起向" + name + "的转账! 元气值将在对方确认后到账。"

                    notification_create(
                        receiver=user,
                        sender=request.user,
                        typename=Notification.Type.NEEDDO,
                        title=Notification.Title.TRANSFER_CONFIRM,
                        content=transaction_msg,
                        URL="/myYQPoint/",
                        relate_TransferRecord=record,
                    )
                    # 跳转回主页, 首先先get主页位置
                    urls = (
                            context["return_url"]
                            + f"?warn_code=2&warn_message={warn_message}"
                    )
                    return redirect(urls)

        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "出现无法预料的问题, 请联系管理员!"

    return render(request, "transaction_page.html", locals())


# 涉及表单，一般就用 post 吧
# 这边先扣，那边先不加，等确认加
# 预期这边成功之后，用企业微信通知接收方，调转到查看未接收记录的窗口
@require_POST
@login_required(redirect_field_name="origin")
def start_transaction(request):
    rid = request.POST.get("rid")  # index
    origin = request.POST.get("origin")
    amount = request.POST.get("amount")
    amount = float(amount)
    transaction_msg = request.POST.get("msg")
    name = request.POST.get("name")
    context = dict()
    context["origin"] = origin

    user = User.objects.get(id=rid)

    try:
        # 允许一位小数
        assert amount == int(float(amount) * 10) / 10
        assert amount > 0
    except:
        context[
            "msg"
        ] = "Unexpected amount. If you are not deliberately doing this, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    try:
        user = User.objects.get(id=rid)
    except:
        context[
            "msg"
        ] = "Unexpected recipient. If you are not deliberately doing this, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    try:
        payer = utils.get_person_or_org(request.user)
        with transaction.atomic():
            if payer.YQPoint >= float(amount):
                payer.YQPoint -= float(amount)
            else:
                raise ValueError
            # TODO 目前用的是 nickname，可能需要改成 name
            # 需要确认 create 是否会在数据库产生记录，如果不会是否会有主键冲突？
            record = TransferRecord.objects.create(
                proposer=request.user, recipient=user
            )
            record.amount = amount
            record.message = transaction_msg
            record.time = str(datetime.now())
            record.save()
            payer.save()

    except:
        context[
            "msg"
        ] = "Check if you have enough YQPoint. If so, please contact the administrator to report this bug."
        return render(request, "msg.html", context)

    context["msg"] = "Waiting the recipient to confirm the transaction."
    return render(request, "msg.html", context)


def confirm_transaction(request, tid=None, reject=None):
    context = dict()
    context["warn_code"] = 1  # 先假设有问题
    with transaction.atomic():
        try:
            record = TransferRecord.objects.select_for_update().get(
                id=tid, recipient=request.user
            )

        except Exception as e:

            context["warn_message"] = "交易遇到问题, 请联系管理员!" + str(e)
            return context

        if record.status != TransferRecord.TransferStatus.WAITING:
            context["warn_message"] = "交易已经完成, 请不要重复操作!"
            return context

        payer = record.proposer
        try:
            if hasattr(payer, "naturalperson"):
                payer = (
                    NaturalPerson.objects.activated()
                        .select_for_update()
                        .get(person_id=payer)
                )
            else:
                payer = Organization.objects.select_for_update().get(
                    organization_id=payer
                )
        except:
            context["warn_message"] = "交易对象不存在或已毕业, 请联系管理员!"
            return context

        recipient = record.recipient
        if hasattr(recipient, "naturalperson"):
            recipient = (
                NaturalPerson.objects.activated()
                    .select_for_update()
                    .get(person_id=recipient)
            )
        else:
            recipient = Organization.objects.select_for_update().get(
                organization_id=recipient
            )

        if reject is True:
            record.status = TransferRecord.TransferStatus.REFUSED
            payer.YQPoint += record.amount
            payer.save()
            context["warn_message"] = "拒绝转账成功!"
            notification_create(
                receiver=record.proposer,
                sender=record.recipient,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.TRANSFER_FEEDBACK,
                content=f"{str(recipient)}拒绝了您的转账。",
                URL="/myYQPoint/",
            )
            notification_status_change(record.transfer_notification.get().id)
        else:
            record.status = TransferRecord.TransferStatus.ACCEPTED
            recipient.YQPoint += record.amount
            recipient.save()
            context["warn_message"] = "交易成功!"
            notification_create(
                receiver=record.proposer,
                sender=record.recipient,
                typename=Notification.Type.NEEDREAD,
                title=Notification.Title.TRANSFER_FEEDBACK,
                content=f"{str(recipient)}接受了您的转账。",
                URL="/myYQPoint/",
            )
            notification_status_change(record.transfer_notification.get().id)
        record.finish_time = datetime.now()  # 交易完成时间
        record.save()
        context["warn_code"] = 2

        return context

    context["warn_message"] = "交易遇到问题, 请联系管理员!"
    return context


def record2Display(record_list, user):  # 对应myYQPoint函数中的table_show_list
    lis = []
    amount = {"send": 0.0, "recv": 0.0}
    # 储存这个列表中所有record的元气值的和
    for record in record_list:
        lis.append({})

        # 确定类型
        record_type = "send" if record.proposer.username == user.username else "recv"

        # id
        lis[-1]["id"] = record.id

        # 时间
        lis[-1]["start_time"] = record.start_time.strftime("%m/%d %H:%M")
        if record.finish_time is not None:
            lis[-1]["finish_time"] = record.finish_time.strftime("%m/%d %H:%M")

        # 对象
        # 如果是给出列表，那么对象就是接收者

        obj_user = record.recipient if record_type == "send" else record.proposer
        lis[-1]["obj_direct"] = "To  " if record_type == "send" else "From"
        if hasattr(obj_user, "naturalperson"):  # 如果OneToOne Field在个人上
            lis[-1]["obj"] = obj_user.naturalperson.name
            lis[-1]["obj_url"] = "/stuinfo/" + \
                                 lis[-1]["obj"] + "+" + str(obj_user.id)
        else:
            lis[-1]["obj"] = obj_user.organization.oname
            lis[-1]["obj_url"] = "/orginfo/" + lis[-1]["obj"]

        # 金额
        lis[-1]["amount"] = record.amount
        amount[record_type] += record.amount

        # 留言
        lis[-1]["message"] = record.message
        lis[-1]["if_act_url"] = False
        if record.corres_act is not None:
            lis[-1]["message"] = "活动" + record.corres_act.title + "积分"
            # TODO 这里还需要补充一个活动跳转链接

        # 状态
        lis[-1]["status"] = record.get_status_display()

    # 对外展示为 1/10
    """
    统一在前端修改
    for key in amount:
        amount[key] = amount[key]/10
    """
    # 由于误差, 将amount调整为小数位数不超过2
    for key in amount.keys():
        amount[key] = round(amount[key], 1)
    return lis, amount


# modified by Kinnuch


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def myYQPoint(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    # 接下来处理POST相关的内容
    html_display["warn_code"] = 0
    if request.method == "POST":  # 发生了交易处理的事件
        try:  # 检查参数合法性
            post_args = request.POST.get("post_button")
            record_id, action = post_args.split(
                "+")[0], post_args.split("+")[1]
            assert action in ["accept", "reject"]
            reject = action == "reject"
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "交易遇到问题,请不要非法修改参数!"

        if html_display["warn_code"] == 0:  # 如果传入参数没有问题
            # 调用确认预约API
            context = confirm_transaction(request, record_id, reject)
            # 此时warn_code一定是1或者2，必定需要提示
            html_display["warn_code"] = context["warn_code"]
            html_display["warn_message"] = context["warn_message"]

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    to_send_set = TransferRecord.objects.filter(
        proposer=request.user, status=TransferRecord.TransferStatus.WAITING
    )

    to_recv_set = TransferRecord.objects.filter(
        recipient=request.user, status=TransferRecord.TransferStatus.WAITING
    )

    issued_send_set = TransferRecord.objects.filter(
        proposer=request.user,
        status__in=[
            TransferRecord.TransferStatus.ACCEPTED,
            TransferRecord.TransferStatus.REFUSED,
        ],
    )

    issued_recv_set = TransferRecord.objects.filter(
        recipient=request.user,
        status__in=[
            TransferRecord.TransferStatus.ACCEPTED,
            TransferRecord.TransferStatus.REFUSED,
        ],
    )

    issued_recv_set = TransferRecord.objects.filter(
        recipient=request.user,
        status__in=[
            TransferRecord.TransferStatus.ACCEPTED,
            TransferRecord.TransferStatus.REFUSED,
        ],
    )

    # to_set 按照开始时间降序排列
    to_set = to_send_set.union(to_recv_set).order_by("-start_time")
    # issued_set 按照完成时间及降序排列
    # 这里应当要求所有已经issued的记录是有执行时间的
    issued_set = issued_send_set.union(
        issued_recv_set).order_by("-finish_time")

    to_list, amount = record2Display(to_set, request.user)
    issued_list, _ = record2Display(issued_set, request.user)

    show_table = {
        "obj": "对象",
        "time": "时间",
        "amount": "金额",
        "message": "留言",
        "status": "状态",
    }

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    # 补充一些呈现信息
    bar_display["title_name"] = "My YQPoint"
    bar_display["navbar_name"] = "我的元气值"  #
    bar_display["help_message"] = local_dict["help_message"]["我的元气值"]

    return render(request, "myYQPoint.html", locals())


"""
页面逻辑：
1. 方法为 GET 时，展示一个活动的详情。
    a. 如果当前用户是个人，有立即报名/已报名的 button
    b. 如果当前用户是组织，并且是该活动的所有者，有修改和取消活动的 button
2. 方法为 POST 时，通过 option 确定操作
    a. 如果修改活动，跳转到 addActivity
    b. 如果取消活动，本函数处理
    c. 如果报名活动，本函数处理 ( 还未实现 )
# TODO
个人操作，包括报名与取消

----------------------------
活动逻辑
1. 活动开始前一小时，不能修改活动
2. 活动开始当天晚上之前，不能再取消活动 ( 目前用的 12 小时，感觉基本差不多 )
"""


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def viewActivity(request, aid=None):
    """
    aname = str(request.POST["aname"])  # 活动名称
    organization_id = request.POST["organization_id"]  # 组织id
    astart = request.POST["astart"]  # 默认传入的格式为 2021-07-21 21:00:00
    afinish = request.POST["afinish"]
    content = str(request.POST["content"])
    URL = str(request.POST["URL"])  # 活动推送链接
    QRcode = request.POST["QRcode"]  # 收取元气值的二维码
    aprice = request.POST["aprice"]  # 活动价格
    capacity = request.POST["capacity"]  # 活动举办的容量
    """
    try:
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
    except:
        return redirect("/welcome/")

    valid, user_type, html_display = utils.check_user_type(request.user)
    
    me = utils.get_person_or_org(request.user, user_type)

    # 活动全部基本信息
    title = activity.title
    """
    org = Organization.objects.activated().get(
        organization_id_id=activity.organization_id_id
    )
    """
    org = activity.organization_id

    org_name = org.oname
    org_avatar_path = utils.get_user_ava(org, "Organization")
    org_type = OrganizationType.objects.get(otype_id=org.otype_id).otype_name
    start_time = activity.start
    end_time = activity.end
    prepare_times = Activity.EndBeforeHours.prepare_times
    apply_deadline = activity.start - \
                     timedelta(hours=prepare_times[activity.endbefore])
    introduction = activity.introduction
    show_url = True # 前端使用量
    aURL = activity.URL
    if aURL is None :
        show_url = False
    aQRcode = activity.QRcode
    bidding = activity.bidding
    price = activity.YQPoint
    current_participants = activity.current_participants
    status = activity.status
    capacity = activity.capacity
    if capacity == -1 or capacity == 10000:
        capacity = "INF"

    # 特判
    person = False
    if user_type == "Person":
        person = True
        try:
            participant = Participant.objects.get(
                activity_id=activity, person_id=me.id
            )
            pStatus = participant.status
        except:
            # 无记录
            pStatus = "无记录"
    ownership = False
    if not person and org.organization_id == request.user:
        ownership = True

    # 新版侧边栏，顶栏等的呈现，采用bar_display，必须放在render前最后一步，但这里render太多了
    # TODO: 整理好代码结构，在最后统一返回
    bar_display = utils.get_sidebar_and_navbar(request.user)
    # 补充一些呈现信息
    bar_display["title_name"] = "活动信息"
    bar_display["navbar_name"] = "活动信息"

    # 处理 get 请求
    if request.method == "GET":
        return render(request, "activity_info.html", locals())

    html_display = dict()
    if request.POST is None:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "非法的 POST 请求。如果您不是故意操作，请联系管理员汇报此 Bug."
        return render(request, "activity_info.html", locals())
    # 处理 post 请求
    # try:
    option = request.POST.get("option")
    if option == "cancel":
        if (
                activity.status == activity.Status.CANCELED
                or activity.status == activity.Status.END
        ):
            html_display["warn_code"] = 1
            html_display["warn_message"] = "当前活动已取消或结束。"
            return render(request, "activity_info.html", locals())

        if activity.status == activity.Status.PROGRESSING:
            if activity.start + timedelta(hours=12) < datetime.now():
                html_display["warn_code"] = 1
                html_display["warn_message"] = "活动已进行 12 小时以上，不能取消。"
                return render(request, "activity_info.html", locals())

        with transaction.atomic():
            org = Organization.objects.select_for_update().get(
                organization_id=request.user
            )
            if bidding:
                participants = Participant.objects.select_for_update().filter(
                    status=Participant.AttendStatus.APLLYING
                )
            else:
                participants = Participant.objects.select_for_update().filter(
                    status=Participant.AttendStatus.APLLYSUCCESS
                )
            records = TransferRecord.objects.select_for_update().filter(
                status=TransferRecord.TransferStatus.ACCEPTED, corres_act=activity
            )
            sumYQPoint = 0.0
            for record in records:
                sumYQPoint += record.amount
            if org.YQPoint < sumYQPoint:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "没有足够的元气值退回给已参与的同学，无法取消活动。"
                return render(request, "activity_info.html", locals())
            else:
                org.YQPoint -= sumYQPoint
                org.save()
                for record in records:
                    proposer = record.proposer
                    proposer = NaturalPerson.objects.select_for_update().get(
                        person_id=proposer
                    )
                    proposer.YQPoint += record.amount
                    record.status = TransferRecord.TransferStatus.REFUND
                    proposer.save()
                    record.save()
                for participant in participants:
                    participant.status = Participant.AttendStatus.APLLYFAILED
                    participant.save()
            activity.status = activity.Status.CANCELED
            activity.save()
        html_display["warn_code"] = 2
        html_display["warn_message"] = "成功取消活动。"
        status = activity.status
        # TODO 第一次点只会提醒已经成功取消活动，但是活动状态还是进行中，看看怎么修一下
        return render(request, "activity_info.html", locals())

    elif option == "edit":
        if (
                activity.status == activity.Status.APPLYING
                or activity.status == activity.Status.REVIEWING
        ):
            return redirect(f"/addActivities/?edit=True&aid={aid}")
        if activity.status == activity.Status.WAITING:
            if start_time + timedelta(hours=1) > datetime.now():
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"活动即将开始, 不能修改活动。"
                return render(request, "activity_info.html", locals())
        else:
            html_display["warn_code"] = 1
            html_display["warn_message"] = f"活动状态为{activity.status}, 不能修改。"
            return render(request, "activity_info.html", locals())

    elif option == "apply":
        aid = request.POST.get("aid")
        willingness = None
        if bidding:
            willingness = request.POST.get("willingness")
            try:
                willingness = float(willingness)
            except:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "请输入投点数值。"
                return render(request, "activity_info.html", locals())
        try:
            context = applyActivity(request, int(aid), willingness)
            if context["success"] == False:
                html_display["warn_code"] = 1
                html_display["warn_message"] = context["msg"]
            else:
                html_display["warn_code"] = 2
                if bidding:
                    html_display["warn_message"] = "投点成功"
                    pStatus = context["pStatus"]
                else:
                    html_display["warn_message"] = "报名成功"
                pStatus = context["pStatus"]
                current_participants += 1
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "非预期的异常，请联系管理员汇报。"
        return render(request, "activity_info.html", locals())

    elif option == "quit":
        with transaction.atomic():
            np = NaturalPerson.objects.select_for_update().get(person_id=request.user)
            org = Organization.objects.select_for_update().get(
                organization_id=activity.organization_id.organization_id
            )
            try:
                participant = Participant.objects.select_for_update().get(
                    activity_id=activity,
                    person_id=np,
                    status__in=[
                        Participant.AttendStatus.APPLYING,
                        Participant.AttendStatus.APLLYSUCCESS,
                    ],
                )
            except:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "未找到报名记录。"
                return render(request, "activity_info.html", locals())
            record = TransferRecord.objects.select_for_update().get(
                corres_act=activity,
                proposer=request.user,
                status=TransferRecord.TransferStatus.ACCEPTED,
            )
            activity = Activity.objects.select_for_update().get(id=aid)

            # 报名截止前，全额退还
            if status == Activity.Status.APPLYING:
                amount = record.amount
            elif status == Activity.Status.WAITING:
                cur_time = datetime.now()
                if cur_time + timedelta(hours=1) > activity.start:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "活动即将开始，不能取消报名。"
                    return render(request, "activity_info.html", locals())
                if bidding:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "投点类活动在报名截止后不能取消。"
                amount = int(10 * record.amount * 0.5) / 10
            else:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "活动已开始或结束，无法取消。"
                return render(request, "activity_info.html", locals())

            if org.YQPoint < amount:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "组织账户元气值不足，请与组织负责人联系。"
                return render(request, "activity_info.html", locals())
            org.YQPoint -= amount
            np.YQPoint += amount
            participant.status = Participant.AttendStatus.CANCELED
            record.status = TransferRecord.TransferStatus.REFUND
            activity.current_participants -= 1
            org.save()
            np.save()
            record.save()
            participant.save()
            activity.save()
            current_participants = activity.current_participants

        html_display["warn_code"] = 2
        html_display["warn_message"] = "成功取消报名。"
        pStatus = Participant.AttendStatus.CANCELED
        return render(request, "activity_info.html", locals())

    elif option == "payment":
        raise NotImplementedError
        return render(request, "activity_info.html", locals())

    else:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "非法的 POST 请求。如果您不是故意操作，请联系管理员汇报此 Bug."
        return render(request, "activity_info.html", locals())

    """
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "非法预期的错误。请联系管理员汇报此 Bug."
        return render(request, "activity_info.html", locals())
    """


# 通过GET获得活动信息表下载链接
# GET参数?activityid=id&infotype=sign[&output=id,name,gender,telephone][&format=csv|excel]
# GET参数?activityid=id&infotype=qrcode
#   activity_id : 活动id
#   infotype    : sign or qrcode or 其他（以后可以拓展）
#     sign报名信息:
#       output  : [可选]','分隔的需要返回的的field名
#                 [默认]id,name,gender,telephone
#       format  : [可选]csv or excel
#                 [默认]csv
#     qrcode签到二维码
# example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=sign
# example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=sign&output=id,wtf
# example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=sign&format=excel
# example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=qrcode
# TODO: 前端页面待对接
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def getActivityInfo(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    

    # check activity existence
    activity_id = request.GET.get("activityid", None)
    try:
        activity = Activity.objects.get(id=activity_id)
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = f"活动{activity_id}不存在"
        return render(request, "某个页面.html", locals())

    # check organization existance and ownership to activity
    organization = utils.get_person_or_org(request.user, "organization")
    if activity.organization_id != organization:
        html_display["warn_code"] = 1
        html_display["warn_message"] = f"{organization}不是活动的组织者"
        return render(request, "某个页面.html", locals())

    info_type = request.GET.get("infotype", None)
    if info_type == "sign":  # get registration information
        # make sure registration is over
        if activity.status == Activity.Status.REVIEWING:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "活动正在审核"
            return render(request, "某个页面.html", locals())

        elif activity.status == Activity.Status.CANCELED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "活动已取消"
            return render(request, "某个页面.html", locals())

        elif activity.status == Activity.Status.APPLYING:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "报名尚未截止"
            return render(request, "某个页面.html", locals())

        else:
            # get participants
            # are you sure it's 'Paticipant' not 'Participant' ??
            participants = Participant.objects.filter(activity_id=activity_id)
            participants = participants.filter(
                status=Participant.AttendStatus.APLLYSUCCESS
            )

            # get required fields
            output = request.GET.get("output", "id,name,gender,telephone")
            fields = output.split(",")

            # check field existence
            allowed_fields = ["id", "name", "gender", "telephone"]
            for field in fields:
                if not field in allowed_fields:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = f"不允许的字段名{field}"
                    return render(request, "某个页面.html", locals())

            filename = f"{activity_id}-{info_type}-{output}"
            content = map(
                lambda paticipant: map(
                    lambda key: paticipant[key], fields), participants
            )

            format = request.GET.get("format", "csv")
            if format == "csv":
                buffer = io.StringIO()
                csv.writer(buffer).writerows(content), buffer.seek(0)
                response = HttpResponse(buffer, content_type="text/csv")
                response["Content-Disposition"] = f"attachment; filename={filename}.csv"
                return response  # downloadable

            elif format == "excel":
                return HttpResponse(".xls Not Implemented")

            else:
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"不支持的格式{format}"
                return render(request, "某个页面.html", locals())

    elif info_type == "qrcode":
        # checkin begins 1 hour ahead
        if datetime.now() < activity.start - timedelta(hours=1):
            html_display["warn_code"] = 1
            html_display["warn_message"] = "签到失败：签到未开始"
            return render(request, "某个页面.html", locals())

        else:
            checkin_url = f"/checkinActivity?activityid={activity.id}"
            origin_url = request.scheme + "://" + request.META["HTTP_HOST"]
            checkin_url = parse.urljoin(
                origin_url, checkin_url)  # require full path

            buffer = io.BytesIO()
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(checkin_url), qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(buffer, "jpeg"), buffer.seek(0)
            response = HttpResponse(buffer, content_type="img/jpeg")
            return response

    else:
        html_display["warn_code"] = 1
        html_display["warn_message"] = f"不支持的信息{info_type}"
        return render(request, "某个页面.html", locals())


# participant checkin activity
# GET参数?activityid=id
#   activity_id : 活动id
# example: http://127.0.0.1:8000/checkinActivity?activityid=1
# TODO: 前端页面待对接
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def checkinActivity(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    

    # check activity existence
    activity_id = request.GET.get("activityid", None)
    try:
        activity = Activity.objects.get(id=activity_id)
        if (
                activity.status != Activity.Status.WAITING
                and activity.status != Activity.Status.PROGRESSING
        ):
            html_display["warn_code"] = 1
            html_display["warn_message"] = f"签到失败：活动{activity.status}"
            return redirect("/viewActivities/")  # context incomplete
    except:
        msg = "活动不存在"
        origin = "/welcome/"
        return render(request, "msg.html", locals())

    # check person existance and registration to activity
    person = utils.get_person_or_org(request.user, "naturalperson")
    try:
        participant = Participant.objects.get(
            activity_id=activity_id, person_id=person.id
        )
        if participant.status == Participant.AttendStatus.APLLYFAILED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有参与这项活动：申请失败"
        elif participant.status == Participant.AttendStatus.APLLYSUCCESS:
            #  其实我觉得这里可以增加一个让发起者设定签到区间的功能
            #    或是有一个管理界面，管理一个“签到开关”的值
            if datetime.now().date() < activity.end.date():
                html_display["warn_code"] = 1
                html_display["warn_message"] = "签到失败：签到未开始"
            elif datetime.now() >= activity.end:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "签到失败：签到已结束"
            else:
                participant.status = Participant.AttendStatus.ATTENDED
                html_display["warn_code"] = 2
                html_display["warn_message"] = "签到成功"
        elif participant.status == Participant.AttendStatus.ATTENDED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "重复签到"
        elif participant.status == Participant.AttendStatus.CANCELED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有参与这项活动：已取消"
        else:
            msg = f"不合理的参与状态：{participant.status}"
            origin = "/welcome/"
            return render(request, "msg.html", locals())
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "您没有参与这项活动：未报名"

    return redirect("/viewActivities/")  # context incomplete


# TODO 定时任务
"""
发起活动与修改活动页
---------------
页面逻辑：
使用 GET 方法时，如果存在 edit=True 参数，展示修改活动的界面，否则展示创建活动的界面。
创建活动的界面，placeholder 为 prompt
编辑活动的界面，表单的 placeholder 会被修改为活动的旧值。并且添加两个 hidden input，分别提交 edit=True 和活动的 id
当请求方法为 POST 时，处理请求并修改数据库，如果没有问题，跳转到展示活动信息的界面
存在 edit=True 参数时，为编辑操作，否则为创建操作
编辑操作时，input 并不包含 model 所有 field 的数据，只修改其中出现的

"""


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def addActivities(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Person":
        return redirect("/welcome/")  # test
    
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理结构，统一在结束时返回render
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建活动"
    bar_display["navbar_name"] = "新建活动"

    if request.method == "POST" and request.POST:

        edit = request.POST.get("edit")
        if edit is not None:
            aid = request.POST.get("aid")
            try:
                aid = int(aid)
                assert edit == "True"
            except:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "非预期的 POST 参数，如果非故意操作，请联系管理员。"
                edit = False
                return render(request, "activity_add.html", locals())

        org = utils.get_person_or_org(request.user, user_type)
        # 和 app.Activity 数据库交互，需要从前端获取以下表单数据
        context = dict()
        context = utils.check_ac_request(request)  # 合法性检查

        if context["warn_code"] != 0:
            html_display["warn_code"] = context["warn_code"]
            html_display["warn_message"] = "创建/修改活动失败。" + context["warn_msg"]
            # return render(request, "activity_add.html", locals())
            # 这里不返回，走到下面 GET 的逻辑，如果是修改，还能展示修改页面

        else:
            with transaction.atomic():
                if edit is not None:
                    # 编辑的情况下，查表取出 activity
                    try:
                        new_act = Activity.objects.select_for_update().get(id=aid)
                    except:
                        html_display["warn_code"] = context["warn_code"]
                        html_display["warn_message"] = "不存在的活动。"
                        edit = False
                        return render(request, "activity_add.html", locals())

                else:
                    # 非编辑，创建一个 activity
                    new_act = Activity.objects.create(
                        title=context["aname"], organization_id=org
                    )
                    if context["signschema"] == 1:
                        new_act.bidding = True
                        new_act.budget = context["budget"]
                    # 默认状态是报名中，可能需要审核
                    if not context["need_check"]:
                        new_act.status = Activity.Status.APPLYING

                # 不一定需要改这些内容，edit 情况下不一定会提交这些内容
                # 如果没有，就不修改
                if context.get("content"):
                    new_act.content = context["content"]
                if context.get("prepare_scheme"):
                    new_act.endbefore = context["prepare_scheme"]
                if context.get("act_start"):
                    new_act.start = context["act_start"]
                if context.get("act_end"):
                    new_act.end = context["act_end"]
                if context.get("URL"):
                    new_act.URL = context["URL"]
                if context.get("location"):
                    new_act.location = context["location"]
                # new_act.QRcode = QRcode
                if context.get("aprice"):
                    new_act.YQPoint = context["aprice"]
                if context.get("capacity"):
                    new_act.capacity = context["capacity"]
                new_act.save()
            if context["warn_code"] == 0:
                return redirect(f"/viewActivity/{new_act.id}")
            # warn_code==0
            return render(request, "activity_add.html", locals())

    # get 请求
    edit = request.GET.get("edit")
    if edit is None or edit != "True":
        # 非编辑，place holder prompt
        edit = False
        title = "活动名称"
        location = "活动地点"
        start = "开始时间"
        end = "结束时间"
        capacity = "人数限制"

        introduction = "(必填)简介会随活动基本信息一同推送至订阅者的微信"
        url = "(可选)填写活动推送的链接"
    else:
        # 编辑状态下，placeholder 为原值
        edit = True
        try:
            aid = request.GET["aid"]
            aid = int(aid)
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "非预期的 GET 参数，如果非故意操作，请联系管理员。"
            edit = False
            return render(request, "activity_add.html", locals())
        activity = Activity.objects.get(id=aid)
        title = activity.title
        budget = activity.budget
        location = activity.location
        start = activity.start.strftime("%m/%d/%Y %H:%M %p")
        end = activity.end.strftime("%m/%d/%Y %H:%M %p")

        introduction = activity.introduction
        url = activity.URL
        endbefore = activity.endbefore
        bidding = activity.bidding
        amount = activity.YQPoint
        signscheme = "先到先得"
        if bidding:
            signscheme = "投点参与"
        capacity = activity.capacity
        no_limit = False
        if capacity == 10000:
            no_limit = True

    # 补充一些实用的信息
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建活动"
    bar_display["navbar_name"] = "新建活动"

    return render(request, "activity_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def subscribeActivities(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
        
    
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    org_list = list(Organization.objects.all())
    otype_list = list(OrganizationType.objects.all())
    unsubscribe_list = list(
        me.unsubscribe_list.values_list("organization_id__username", flat=True)
    )  # 获取不订阅列表（数据库里的是不订阅列表）
    subscribe_list = [
        org.organization_id.username for org in org_list if org.organization_id.username not in unsubscribe_list

    ]  # 获取订阅列表
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    # 补充一些呈现信息
    bar_display["title_name"] = "Subscribe"
    bar_display["navbar_name"] = "我的订阅"  #
    bar_display["help_message"] = local_dict["help_message"]["我的订阅"]

    subscribe_url = reverse("save_subscribe_status")
    return render(request, "activity_subscribe.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def save_subscribe_status(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    me = utils.get_person_or_org(request.user, user_type)
    params = json.loads(request.body.decode("utf-8"))
    print(params)
    with transaction.atomic():
        if "id" in params.keys():
            if params["status"]:
                me.unsubscribe_list.remove(
                    Organization.objects.get(
                        organization_id__username=params["id"])
                )
            else:
                me.unsubscribe_list.add(
                    Organization.objects.get(
                        organization_id__username=params["id"])
                )
        elif "otype" in params.keys():
            unsubscribed_list = me.unsubscribe_list.filter(
                otype__otype_id=params["otype"]
            )
            org_list = Organization.objects.filter(
                otype__otype_id=params['otype'])
            if params["status"]:  # 表示要订阅
                for org in unsubscribed_list:
                    me.unsubscribe_list.remove(org)
            else:  # 不订阅
                for org in org_list:
                    me.unsubscribe_list.add(org)
        me.save()

    return JsonResponse({"success": True})


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def apply_position(request, oid=None):
    """ apply for position in organization, including join, withdraw, transfer
    Args:
        - oid <str>: Organization ID in URL path, while actually is the ID of User.
        - apply_type <str>: Application type, including "JOIN", "WITHDRAW", "TRANSFER".
        - apply_pos <int>: Position applied for.
    Return:
        - Personal `/notification/` web page
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type != "Person":
        return redirect("/index/")
    
    
    me = utils.get_person_or_org(request.user, user_type)
    user = User.objects.get(id=int(oid))
    org = Organization.objects.get(organization_id=user)

    if request.method == "GET":
        apply_type = request.GET.get("apply_type", "JOIN")
        apply_pos = int(request.GET.get("apply_pos", 10))
    elif request.method == "POST":
        apply_type = request.POST.get("apply_type", "JOIN")
        apply_pos = int(request.POST.get("apply_pos", 10))

    try:
        apply_type = Position.objects.create_application(me, org, apply_type, apply_pos)
    except Exception as e:
        print(e)
        return redirect(f"/orginfo/{org.oname}?warn_code=1&warn_message={e}")

    contents = [f"{apply_type}申请已提交审核", f"{apply_type}申请审核"]
    notification_create(
        me.person_id,
        org.organization_id,
        Notification.Type.NEEDREAD,
        Notification.Title.POSITION_INFORM,
        contents[0],
        "/personnelMobilization/",

        publish_to_wechat=True,  # 不要复制这个参数，先去看函数说明
    )
    notification_create(
        org.organization_id,
        me.person_id,
        Notification.Type.NEEDDO,
        Notification.Title.POSITION_INFORM,
        contents[1],
        "/personnelMobilization/",

        publish_to_wechat=True,  # 不要复制这个参数，先去看函数说明
    )
    return redirect("/notifications/")


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def personnel_mobilization(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type != "Organization":
        return redirect("/index/")
    
    me = utils.get_person_or_org(request.user, user_type)
    html_display = {"is_myself": True}

    if request.method == "GET":  # 展示页面
        pending_status = Q(apply_status=Position.ApplyStatus.PENDING)
        issued_status = (
                Q(apply_status=Position.ApplyStatus.PASS)
                | Q(apply_status=Position.ApplyStatus.REJECT)
        )

        pending_list = me.position_set.filter(pending_status)
        for record in pending_list:
            record.job_name = me.otype.get_name(record.apply_pos)

        issued_list = me.position_set.filter(issued_status)
        for record in issued_list:
            record.job_name = me.otype.get_name(record.pos)

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
        bar_display = utils.get_sidebar_and_navbar(request.user)
        bar_display["title_name"] = "人事变动"
        bar_display["navbar_name"] = "人事变动"

        return render(request, "personnel_mobilization.html", locals())

    elif request.method == "POST":  # 审核申请
        params = json.loads(request.POST.get("confirm", None))
        if params is None:
            redirect(f"/orginfo/{me.oname}")

        with transaction.atomic():
            application = Position.objects.select_for_update().get(
                id=params["id"])
            apply_status = params["apply_status"]
            if apply_status == "PASS":
                if application.apply_type == Position.ApplyType.JOIN:
                    application.status = Position.Status.INSERVICE
                    application.pos = application.apply_pos
                elif application.apply_type == Position.ApplyType.WITHDRAW:
                    application.status = Position.Status.DEPART
                elif application.apply_type == Position.AppltType.TRANSFER:
                    application.pos = application.apply_pos
                application.apply_status = Position.ApplyStatus.PASS
            elif apply_status == "REJECT":
                application.apply_status = Position.ApplyStatus.REJECT
            application.save()

        notification_create(
            application.person.person_id,
            me.organization_id,
            Notification.Type.NEEDREAD,
            Notification.Title.POSITION_INFORM,
            f"{application.apply_type}申请{application.apply_status}",

            publish_to_wechat=True,  # 不要复制这个参数，先去看函数说明
        )
        return redirect("/personnelMobilization/")


def notification2Display(notification_list):
    lis = []
    # 储存这个列表中所有record的元气值的和
    for notification in notification_list:
        lis.append({})

        # id
        lis[-1]["id"] = notification.id

        # 时间
        lis[-1]["start_time"] = notification.start_time.strftime("%m/%d %H:%M")
        if notification.finish_time is not None:
            lis[-1]["finish_time"] = notification.finish_time.strftime(
                "%m/%d %H:%M")

        # 留言
        lis[-1]["content"] = notification.content

        # 状态
        lis[-1]["status"] = notification.get_status_display()
        lis[-1]["URL"] = notification.URL
        lis[-1]["type"] = notification.get_typename_display()
        lis[-1]["title"] = notification.get_title_display()
        if notification.sender.username[0] == "z":
            lis[-1]["sender"] = Organization.objects.get(
                organization_id__username=notification.sender.username
            ).oname
        else:
            lis[-1]["sender"] = NaturalPerson.objects.get(
                person_id__username=notification.sender.username
            ).name
    return lis


def notification_status_change(notification_id):
    """
    调用该函数以完成一项通知。对于知晓类通知，在接收到用户点击按钮后的post表单，该函数会被调用。
    对于需要完成的待处理通知，需要在对应的事务结束判断处，调用该函数。
    """
    context = dict()
    context["warn_code"] = 1
    with transaction.atomic():
        notification = Notification.objects.select_for_update().get(id=notification_id)
        if notification.status == Notification.Status.UNDONE:
            notification.status = Notification.Status.DONE
            notification.finish_time = datetime.now()  # 通知完成时间
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "您已成功阅读一条通知！"
        elif notification.status == Notification.Status.DONE:
            notification.status = Notification.Status.UNDONE
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "成功设置一条通知为未读！"
        return context
    context["warn_message"] = "在阅读通知的过程中发生错误，请联系管理员！"
    return context


def notification_create(
        receiver, sender, typename, title, content, URL=None, relate_TransferRecord=None
        , *, publish_to_wechat=False
):
    """
    对于一个需要创建通知的事件，请调用该函数创建通知！
        receiver: org 或 nat_person，使用object.get获取的 user 对象
        sender: org 或 nat_person，使用object.get获取的 user 对象
        type: 知晓类 或 处理类
        title: 请在数据表中查找相应事件类型，若找不到，直接创建一个新的choice
        content: 输入通知的内容
        URL: 需要跳转到处理事务的页面

    注意事项：
        publish_to_wechat: bool 仅关键字参数
        - 你不应该输入这个参数，除非你清楚wechat_send.py的所有逻辑
        - 在最坏的情况下，可能会阻塞近10s
        - 简单来说，涉及订阅或者可能向多人连续发送类似通知时，都不要发送到微信
        - 在线程锁或原子锁内时，也不要发送
        
    现在，你应该在不急于等待的时候显式调用publish_notification(s)这两个函数，
        具体选择哪个取决于你创建的通知是一批类似通知还是单个通知
    """
    notification = Notification.objects.create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
        URL=URL,
        relate_TransferRecord=relate_TransferRecord,
    )
    if publish_to_wechat == True:
        if getattr(publish_notification, 'ENABLE_INSTANCE', False):
            publish_notification(notification)
        else:
            publish_notification(notification.id)
    return notification



@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def notifications(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    # 接下来处理POST相关的内容

    if request.method == "GET" and request.GET:  # 外部错误信息
        try: 
            warn_code = int(request.GET["warn_code"])
            assert warn_code in [1, 2]
            warn_message = str(request.GET.get("warn_message"))
            html_display["warn_code"] = warn_code
            html_display["warn_message"] = warn_message
        except: 
            html_display["warn_code"] = 1
            html_display["warn_message"] = "非预期的GET参数"

    if request.method == "POST":  # 发生了通知处理的事件
        post_args = request.POST.get("post_button")
        if 'cancel' in post_args:
            notification_id = int(post_args.split("+")[0])
            Notification.objects.get(id=notification_id).delete()
            html_display["warn_code"] = 2 # success
            html_display['warn_message'] = '成功删除一条通知！'
        else:
            notification_id = post_args
            context = notification_status_change(notification_id)
            html_display["warn_code"] = context["warn_code"]
            html_display["warn_message"] = context["warn_message"]
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    done_set = Notification.objects.filter(
        receiver=request.user, status=Notification.Status.DONE
    )

    undone_set = Notification.objects.filter(
        receiver=request.user, status=Notification.Status.UNDONE
    )

    done_list = notification2Display(
        list(done_set.union(done_set).order_by("-finish_time"))
    )
    undone_list = notification2Display(
        list(undone_set.union(undone_set).order_by("-start_time"))
    )

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Notifications"
    bar_display["navbar_name"] = "通知信箱"
    bar_display["help_message"] = local_dict["help_message"]["通知信箱"]

    return render(request, "notifications.html", locals())


# 新建组织 or 修改新建组织信息
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def addOrganization(request):
    """
    新建组织，首先是由check_neworg_request()检查输入的合法性，再存储申请信息到NewOrganization的一个实例中
    之后便是创建给对应审核老师的通知
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        return redirect("/welcome/")  # test
    
    me = utils.get_person_or_org(request.user, user_type)
    
    html_display['is_myself'] = True

    edit = 0
    if request.GET.get('neworg_id') is not None and request.GET.get('notifi_id') is not None:
        edit = 1
        try:
            id = int(request.GET.get('neworg_id'))  # 新建组织ID
            notification_id = int(request.GET.get('notifi_id'))  # 通知ID
            en_pw = str(request.GET.get('enpw'))
            if hash_coder.verify(str(id) + '新建组织' + str(notification_id),
                                en_pw) == False:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
            preorg = NewOrganization.objects.get(id=id)

            notification=Notification.objects.get(id=notification_id)
            if preorg.status==NewOrganization.NewOrgStatus.CANCELED or preorg.status==NewOrganization.NewOrgStatus.CONFIRMED \
                    or notification.status==Notification.Status.DONE:
                if notification.status == Notification.Status.UNDONE:
                    notification_status_change(notification_id)
                html_display['warn_code'] = 1
                html_display['warn_message'] = "通知已被处理，请不要重复处理。"
                return redirect('/notifications/' + 
                    '?warn_code={}&warn_message={}'.format(
                        html_display['warn_code'], html_display['warn_message']))
        except:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
            return redirect('/notifications/' + 
                '?warn_code={}&warn_message={}'.format(
                    html_display['warn_code'], html_display['warn_message']))

    
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织"
    bar_display["navbar_name"] = "新建组织"


    if edit:  # 打开页面信息的准备
        comments = preorg.comments.order_by("time")
        html_display['oname'] = preorg.oname
        html_display['otype_id'] = preorg.otype.otype_id
        html_display['pos'] = preorg.pos
        html_display['introduction'] = preorg.introduction
        html_display['application'] = preorg.application
        org_avatar_path=utils.get_user_ava(preorg, "Organization")

    if request.method == "POST" and request.POST:

        if request.POST.get('comment_submit') is not None:  # 新建评论信息，并保存
            text = str(request.POST.get('comment'))
            #检查图片合法性
            comment_images = request.FILES.getlist('comment_images')
            if len(comment_images) > 0:
                for comment_image in comment_images:
                    if utils.if_image(comment_image) == False:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "上传的附件只支持图片格式。"
                        return render(request, "organization_audit.html", locals())
            try:

                with transaction.atomic():
                    org_comment = Comment.objects.create(commentbase=preorg, commentator=request.user, text=text)
                    if len(comment_images) > 0:
                        for comment_image in comment_images:
                            CommentPhoto.objects.create(image=comment_image, comment=org_comment)
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "评论失败，请联系管理员。"
                return render(request, "organization_audit.html", locals())

        else:
            # 参数合法性检查
            context = utils.check_neworg_request(request)  # check
            if context['warn_code'] != 0:
                html_display['warn_code'] = context['warn_code']
                html_display['warn_message'] = "新建组织申请失败。" + context['warn_msg']
                return render(request, "organization_add.html", locals())

            # 新建组织申请
            if edit == 0:

                try:
                    with transaction.atomic():
                        new_org = NewOrganization.objects.create(oname=context['oname'], otype=context['otype'],
                                                                 pos=context['pos'])
                        new_org.introduction = context['introduction']
                        new_org.avatar = context['avatar']
                        new_org.application = context['application']
                        new_org.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建预备组织信息失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                try:
                    with transaction.atomic():
                        content = "新建组织申请：“{oname}”{otype_name}".format(
                            oname=new_org.oname, otype_name=new_org.otype.otype_name)
                        username = local_dict["audit_teacher"]["Neworg"]  # 在local_json.json新增审批人员信息,暂定为YPadmin
                        Auditor = User.objects.get(username=username)
                        URL = ""

                        new_notification = notification_create(Auditor, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)
                        en_pw = hash_coder.encode(str(new_org.id) + '新建组织' + 
                                                    str(new_notification.id))
                        URL = "/auditOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=new_org.id, nid=new_notification.id,en_pw=en_pw)
                        URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)

                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功发送，请耐心等待主管老师审批！"
                return render(request, "organization_add.html", locals())


            # 修改组织申请
            else:
                # 修改信息
                try:
                    with transaction.atomic():
                        preorg.oname = context['oname']
                        preorg.otype = context['otype']
                        preorg.introduction = context['introduction']

                        if context['avatar']is not None:
                            preorg.avatar = context['avatar']
                        preorg.application = context['application']
                        preorg.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "修改申请失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                # 发送通知
                try:
                    with transaction.atomic():
                        content = "“{oname}”{otype_name}修改了申请材料，请您继续审核！".format(
                            oname=preorg.oname, otype_name=preorg.otype.otype_name)
                        username = local_dict["audit_teacher"]["Neworg"]  # 在local_json.json新增审批人员信息,暂定为YPadmin
                        Auditor = User.objects.get(username=username)
                        URL = ""

                        new_notification = notification_create(Auditor, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)
                        en_pw = hash_coder.encode(str(preorg.id) + '新建组织' + 
                                                    str(new_notification.id))
                        URL = "/auditOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=preorg.id, nid=new_notification.id, en_pw=en_pw)
                        URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                context = notification_status_change(notification_id)
                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功发送，请耐心等待主管老师审批！"
                if context['warn_code'] != 0:
                    html_display['warn_message'] = context['warn_message']

                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)

                return redirect('/notifications/' + 
                    '?warn_code={}&warn_message={}'.format(
                        html_display['warn_code'], html_display['warn_message']))


    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织"
    bar_display["navbar_name"] = "新建组织"
    return render(request, "organization_add.html", locals())


# 修改和审批申请新建组织的信息，只用该函数即可
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def auditOrganization(request):
    """
    对于审核老师老师：第一次进入的审核，如果申请需要修改，则有之后的下一次审核等
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    
    me = utils.get_person_or_org(request.user, user_type)
    html_display['is_myself'] = True
    html_display['warn_code'] = 0

    if request.user.username != local_dict["audit_teacher"]["Neworg"]:
        return redirect('/notifications/')

    try:  # 获取申请信息
        id = int(request.GET.get('neworg_id', -1))  # 新建组织ID
        notification_id = int(request.GET.get('notifi_id', -1))  # 通知ID
        if id == -1 or notification_id == -1:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
            return redirect('/notifications/' +
                '?warn_code={}&warn_message={}'.format(
                    html_display['warn_code'], html_display['warn_message']))
        en_pw = str(request.GET.get('enpw'))
        if hash_coder.verify(str(id) + '新建组织' + str(notification_id),
                            en_pw) == False:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
        preorg = NewOrganization.objects.get(id=id)
        notification = Notification.objects.get(id=notification_id)
        if preorg.status == NewOrganization.NewOrgStatus.CANCELED or preorg.status == NewOrganization.NewOrgStatus.CONFIRMED \
                or notification.status == Notification.Status.DONE:
            if notification.status == Notification.Status.UNDONE:
                notification_status_change(notification_id)
            html_display['warn_code'] = 1
            html_display['warn_message'] = "通知已被处理，请不要重复处理。"
            return redirect('/notifications/' + 
                '?warn_code={}&warn_message={}'.format(
                    html_display['warn_code'], html_display['warn_message']))
    except:
        html_display['warn_code'] = 1
        html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
        return redirect('/notifications/' + 
            '?warn_code={}&warn_message={}'.format(
                html_display['warn_code'], html_display['warn_message']))


    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织审核"
    bar_display["navbar_name"] = "新建组织审核"

    if request.method == "POST" and request.POST:
        if request.POST.get('comment_submit') is not None:  # 新建评论信息，并保存
            text = str(request.POST.get('comment'))
            # 检查图片合法性
            comment_images = request.FILES.getlist('comment_images')
            if len(comment_images) > 0:
                for comment_image in comment_images:
                    if utils.if_image(comment_image) == False:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "上传的附件只支持图片格式。"
                        return render(request, "organization_audit.html", locals())
            try:
                with transaction.atomic():
                    org_comment = Comment.objects.create(commentbase=preorg, commentator=request.user, text=text)
                    if len(comment_images) > 0:
                        for comment_image in comment_images:
                            CommentPhoto.objects.create(image=comment_image, comment=org_comment)
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "评论失败，请联系管理员。"
                return render(request, "organization_audit.html", locals())

        # 对于审核老师来说，有三种操作，通过，申请需要修改和拒绝
        else:
            submit = int(request.POST.get('submit', -1))

            if submit == 1:  # 修改
                try:  # 发送给申请者的需要修改通知
                    with transaction.atomic():

                        content = "新建组织申请信息需要修改！"
                        receiver = preorg.pos  # 通知接收者
                        URL = ""
                        new_notification = notification_create(receiver, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)
                        en_pw = hash_coder.encode(str(preorg.id) + '新建组织' +
                                                    str(new_notification.id))
                        URL = "/addOrganization/?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=preorg.id, nid=new_notification.id, en_pw=en_pw)
                        URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())
                context = notification_status_change(notification_id)
                html_display['warn_code'] = 2
                html_display['warn_message'] = context['warn_message']
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                return redirect('/notifications/' +
                    '?warn_code={}&warn_message={}'.format(
                        html_display['warn_code'], html_display['warn_message']))
            if submit == 2:  # 通过

                try:
                    with transaction.atomic():  # 新建组织

                        username = utils.find_max_oname()  # 组织的代号最大值

                        user = User.objects.create(username=username)
                        password = local_dict["testword"]["test"]
                        user.set_password(password)  # 统一密码
                        user.save()

                        org = Organization.objects.create(
                            organization_id=user, otype=preorg.otype
                        )  # 实质创建组织
                        org.oname = preorg.oname
                        org.YQPoint = 0.0
                        org.introduction = preorg.introduction
                        org.avatar = preorg.avatar
                        org.save()

                        charger = utils.get_person_or_org(preorg.pos)  # 负责人
                        pos = Position.objects.create(person=charger, org=org)
                        pos.save()

                        preorg.status = preorg.NewOrgStatus.CONFIRMED
                        preorg.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建组织失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())

                try:  # 发送给申请者的通过通知
                    with transaction.atomic():
                        content = "新建组织申请已通过，组织代号为 “{username}” ，初始密码为 “{password}” ，请尽快修改密码。" \
                            .format(username=username, password=password)
                        receiver = preorg.pos  # 通知接收者
                        URL = "/notifications/"
                        URL = request.build_absolute_uri(URL)
                        """# 如果老师另留有评论的话,将评论放在content里
                        comments = preorg.comment
                        text = ""
                        for comment in comments.all():
                            text += comment.text
                        content += " 老师给你留言啦："
                        content += text"""

                        new_notification=notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                            Notification.Title.VERIFY_INFORM, content, URL)

                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())

                context = notification_status_change(notification_id)
                # 成功新建组织
                html_display['warn_code'] = 2
                html_display['warn_message'] = "已通过新建组织申请，组织已创建！"
                if context['warn_code'] != 0:
                    html_display['warn_message'] = context['warn_message']
                #微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                return redirect('/notifications/' +
                    '?warn_code={}&warn_message={}'.format(
                        html_display['warn_code'], html_display['warn_message']))
            elif submit == 3:  # 拒绝
                try:  # 发送给申请者的拒绝通知
                    with transaction.atomic():
                        preorg.status = preorg.NewOrgStatus.CANCELED
                        preorg.save()
                        content = "很遗憾，新建组织申请未通过！"
                        receiver = preorg.pos  # 通知接收者
                        URL = "/notifications/"
                        URL = request.build_absolute_uri(URL)
                        """# 如果老师另留有评论的话,将评论放在content里
                        comments = preorg.comment
                        text = ""
                        for comment in comments.all():
                            text += comment.text
                        content += " 老师给你留言啦："
                        content += text"""

                        new_notification = notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                            Notification.Title.VERIFY_INFORM, content, URL)

                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())

                context = notification_status_change(notification_id)
                # 成功拒绝新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "已拒绝新建组织的请求！"
                if context['warn_code'] != 0:
                    html_display['warn_message'] = context['warn_message']
                # 微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                return redirect('/notifications/' +
                    '?warn_code={}&warn_message={}'.format(
                        html_display['warn_code'], html_display['warn_message']))
            else:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "系统出现问题，请联系管理员"
                return redirect('/notifications/' +
                    '?warn_code={}&warn_message={}'.format(
                        html_display['warn_code'], html_display['warn_message']))
    #以下需要在前端呈现
    comments = preorg.comments.order_by('time')  # 加载评论
    html_display['oname'] = preorg.oname
    html_display['otype_name'] = preorg.otype.otype_name
    html_display['pos'] = preorg.pos
    html_display['introduction'] = preorg.introduction
    html_display['application'] = preorg.application
    org_avatar_path = utils.get_user_ava(preorg, "Organization")

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织审核"
    bar_display["navbar_name"] = "新建组织审核"

    return render(request, "organization_audit.html", locals())


# 新建或修改报销信息
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def addReimbursement(request):
    """
    新建报销信息
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Person":
        return redirect("/welcome/")  # test
    
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    html_display['warn_code'] = 0

    edit = 0
    reimbursed_act_ids = Reimbursement.objects.all(
        ).exclude(status=Reimbursement.ReimburseStatus.CANCELED     # 未取消报销的
        # ).filter(status=Reimbursement.ReimburseStatus.CONFIRMED     # 已报销完的
        ).values_list('activity_id', flat=True)
    activities = Activity.objects.activated(    # 本学期的
        ).filter(organization_id=me             # 本部门组织的
        ).filter(status=Activity.Status.END     # 已结束的
        ).exclude(id__in=reimbursed_act_ids     # 还没有报销的
        )                                       # 这种写法是为了方便随时取消某个条件

    """unreim_acts=Activity.objects.activated().exclude(reimbursement__status=Reimbursement.ReimburseStatus.CANCELED)
    #unreim_acts=Reimbursement.objects.exclude(status=Reimbursement.ReimburseStatus.CANCELED).activity
    activities=activities.difference(unreim_acts)"""
    YQP = float(me.YQPoint)  # 组织剩余的元气值
    #新版侧边栏, 顶栏等的呈现，采用
    #bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建报销申请"
    bar_display["navbar_name"] = "新建报销申请"

    # 如果是修改，则加载报销信息
    if request.GET.get('reimb_id') is not None and request.GET.get('notifi_id') is not None:
        edit = 1  # 表示需要修改报销信息
        try:
            id = int(request.GET.get('reimb_id'))  # 报销信息的ID
            notification_id = int(request.GET.get('notifi_id'))  # 通知ID
            en_pw = str(request.GET.get('enpw'))
            if hash_coder.verify(str(id) + '新建报销' + str(notification_id),
                                en_pw) == False:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
            pre_reimb = Reimbursement.objects.get(id=id)
            notification=Notification.objects.get(id=notification_id)
            if pre_reimb.status==Reimbursement.ReimburseStatus.CONFIRMED \
                    or pre_reimb.status==Reimbursement.ReimburseStatus.CANCELED \
                    or notification.status==Notification.Status.DONE:
                if notification.status==Notification.Status.UNDONE:
                    notification_status_change(notification_id)
                html_display['warn_code'] = 1
                html_display['warn_message'] = "该条通知已处理，请勿重复处理。"
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
        except:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
    if edit:  # 第一次打开页面信息的准备工作,以下均为前端展示需要
        comments = pre_reimb.comments.order_by("time")
        html_display['activity'] = pre_reimb.activity
        html_display['amount'] = pre_reimb.amount  # 报销金额
        html_display['message'] = pre_reimb.message  # 备注信息

    if request.method == "POST" and request.POST:

        if request.POST.get('comment_submit') is not None:  # 新建评论信息，并保存
            text = str(request.POST.get('comment'))
            # 检查图片合法性
            comment_images = request.FILES.getlist('comment_images')
            if len(comment_images) > 0:
                for comment_image in comment_images:
                    if utils.if_image(comment_image) == False:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "上传的附件只支持图片格式。"
                        return render(request, "organization_audit.html", locals())
            try:
                with transaction.atomic():
                    reim_comment = Comment.objects.create(commentbase=pre_reimb, commentator=request.user, text=text)
                    if len(comment_images) > 0:
                        for comment_image in comment_images:
                            CommentPhoto.objects.create(image=comment_image, comment=reim_comment)
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "评论失败，请联系管理员。"
                return render(request, "reimbursement_add.html", locals())
        else:  # POST信息获取

            # 活动实例
            try:
                reimb_act_id = int(request.POST.get('activity_id'))
                reimb_act = Activity.objects.get(id=reimb_act_id)
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "找不到该活动，请检查报销的活动的合法性！"
                return render(request, "reimbursement_add.html", locals())
            # YQP合法性的检查
            try:
                reimb_YQP = float(request.POST.get('YQP'))
                if reimb_YQP > YQP:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "申请失败，报销的元气值不能超过组织当前元气值！"
                    return render(request, "reimbursement_add.html", locals())
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "输入的元气值的格式不正确，请联系管理员"
                return render(request, "reimbursement_add.html", locals())
            # 报销材料图片的保存

            message = request.POST.get('message')  # 备注信息

            if edit == 0:


                try:  # 创建报销信息
                    images = request.FILES.getlist('images')
                    for image in images:
                        if utils.if_image(image) == False:
                            html_display['warn_code'] = 1
                            html_display['warn_message'] = "上传的附件只支持图片格式。"
                            return render(request, "reimbursement_add.html", locals())
                    with transaction.atomic():
                        new_reimb = Reimbursement.objects.create(activity=reimb_act, amount=reimb_YQP, pos=request.user)
                        new_reimb.message = message
                        new_reimb.save()
                        # 创建评论保存图片
                        text = "以下默认为初始的报销材料"
                        reim_comment = Comment.objects.create(commentbase=new_reimb, commentator=request.user)
                        reim_comment.text = text
                        reim_comment.save()
                        for payload in images:
                            CommentPhoto.objects.create(image=payload, comment=reim_comment)
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "新建报销失败，请联系管理员！"
                    return render(request, "reimbursement_add.html", locals())

                try:  # 创建对应通知
                    with transaction.atomic():
                        content = "有{org_name}新的报销申请！".format(org_name=me.oname)
                        username = local_dict["audit_teacher"]["Funds"]  # 在local_json.json新增审批人员信息,暂定为YPadmin
                        Auditor = User.objects.get(username=username)
                        URL = ""
                        new_notification = notification_create(Auditor, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)
                        en_pw = hash_coder.encode(str(new_reimb.id) + '新建报销' + 
                                                    str(new_notification.id))
                        URL = "/auditReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=new_reimb.id, nid=new_notification.id, en_pw=en_pw)
                        URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "reimbursement_add.html", locals())
                #微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                # 成功发送报销申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功发送，请耐心等待主管老师审批！"
                return render(request, "reimbursement_add.html", locals())

            else:  # 修改报销申请，只有图片和备注信息可以修改

                # 修改信息
                try:
                    with transaction.atomic():
                        pre_reimb.message = message
                        pre_reimb.amount = reimb_YQP
                        pre_reimb.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "修改申请失败。请检查输入or联系管理员"
                    return render(request, "orgnization_add.html", locals())

                # 发送修改的申请通知
                try:
                    with transaction.atomic():
                        content = "{org_name}的报销申请已修改！".format(org_name=me.oname)
                        username = local_dict["audit_teacher"]["Funds"]  # 在local_json.json新增审批人员信息,暂定为YPadmin
                        Auditor = User.objects.get(username=username)
                        URL = ""
                        new_notification = notification_create(Auditor, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)

                        en_pw = hash_coder.encode(str(pre_reimb.id) + '新建报销' + 
                                                    str(new_notification.id))
                        URL = "/auditReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=pre_reimb.id, nid=new_notification.id, en_pw=en_pw)
                        URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "reimbursement_add.html", locals())

                context = notification_status_change(notification_id)  # 通知状态修改
                html_display['warn_code'] = context['warn_code']
                html_display['warn_message'] = context['warn_message']
                # 成功修改报销申请
                if context['warn_code'] == 2:
                    html_display['warn_message'] = "申请已成功发送，请耐心等待主管老师审批！"
                #发送微信消息
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                return redirect('/notifications/', locals())

        return render(request, "reimbursement_add.html", locals())
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建报销审核"
    bar_display["navbar_name"] = "新建报销审核"
    return render(request, "reimbursement_add.html", locals())


# 审核报销信息
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def auditReimbursement(request):
    """
    审核报销信息
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        return redirect("/welcome/")  # test
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    html_display['warn_code'] = 0
    html_display['warn_message'] = ""

    #检查是否为正确的审核老师
    if request.user.username != local_dict["audit_teacher"]["Funds"]:
        return redirect('/notifications/')

    try:  # 获取申请信息
        id = int(request.GET.get('reimb_id', -1))  # 报销信息的ID
        notification_id = int(request.GET.get('notifi_id', -1))  # 通知ID

        if id == -1 or notification_id == -1:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
        en_pw = str(request.GET.get('enpw'))
        if hash_coder.verify(str(id) + '新建报销' + str(notification_id),
                            en_pw) == False:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
        new_reimb = Reimbursement.objects.get(id=id)
        notification = Notification.objects.get(id=notification_id)
        if new_reimb.status == Reimbursement.ReimburseStatus.CONFIRMED \
                or new_reimb.status == Reimbursement.ReimburseStatus.CANCELED \
                or notification.status == Notification.Status.DONE:
            if notification.status == Notification.Status.UNDONE:
                notification_status_change(notification_id)
            html_display['warn_code'] = 1
            html_display['warn_message'] = "该条通知已处理，请勿重复处理。"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))

    except:
        html_display['warn_code'] = 1
        html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
        return redirect('/notifications/' +
                        '?warn_code={}&warn_message={}'.format(
                            html_display['warn_code'], html_display['warn_message']))

    # 新版侧边栏, 顶栏等的呈现，采用
    # bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "报销审核"
    bar_display["navbar_name"] = "报销审核"

    if request.method == "POST" and request.POST:

        if request.POST.get('comment_submit') is not None:  # 新建评论信息，并保存
            text = str(request.POST.get('comment'))
            # 检查图片合法性
            comment_images = request.FILES.getlist('comment_images')
            if len(comment_images) > 0:
                for comment_image in comment_images:
                    if utils.if_image(comment_image) == False:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "上传的附件只支持图片格式。"
                        return render(request, "organization_audit.html", locals())
            try:
                with transaction.atomic():
                    reim_comment = Comment.objects.create(commentbase=new_reimb, commentator=request.user, text=text)
                    if len(comment_images) > 0:
                        for comment_image in comment_images:
                            CommentPhoto.objects.create(image=comment_image, comment=reim_comment)
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "评论失败，请联系管理员。"
                return render(request, "reimbursement_comment.html", locals())
        # 对于审核老师来说，有三种操作，通过，申请需要修改和拒绝
        else:

            submit = int(request.POST.get('submit', -1))
            if submit == 1:  # 修改
                try:  # 发送给申请者的需要修改通知
                    with transaction.atomic():

                        content = "递交的报销需要修改！"
                        receiver = new_reimb.pos  # 通知接收者
                        URL = ""
                        new_notification = notification_create(receiver, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)
                        en_pw = hash_coder.encode(str(new_reimb.id) + '新建报销' + 
                                                    str(new_notification.id))
                        URL = "/addReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=new_reimb.id, nid=new_notification.id, en_pw=en_pw)
                        URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())
                context = notification_status_change(notification_id)
                #发送微信消息
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                html_display['warn_code'] = context['warn_code']
                html_display['warn_message'] = context['warn_message']
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
            if submit == 2:  # 通过
                org = new_reimb.pos.organization

                try:
                    with transaction.atomic():
                        if org.YQPoint < new_reimb.amount:
                            html_display['warn_code'] = 1
                            html_display['warn_message'] = "当前组织没有足够的元气值。报销申请无法通过，请联系管理员！"
                        else:  # 修改对应组织的元气值
                            org.YQPoint -= new_reimb.amount
                            org.save()
                            new_reimb.status = Reimbursement.ReimburseStatus.CONFIRMED
                            new_reimb.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "修改元气值失败。报销申请无法通过，请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())


                try:  # 发送给申请者的通过通知或者是没有足够元气值的通知
                    with transaction.atomic():
                        if html_display['warn_code'] == 1:
                            content = "报销申请已通过，但是组织元气值不足以扣除，请补充元气值至{amount}以上再点击通知继续申请！".format(
                                amount=new_reimb.amount)
                            typename = Notification.Type.NEEDDO
                            URL = ""
                        else:
                            content = "报销申请已通过，扣除元气值{amount}".format()
                            typename = Notification.Type.NEEDREAD
                            URL = "/notifications/"
                            URL = request.build_absolute_uri(URL)
                        receiver = new_reimb.pos  # 通知接收者
                        # TODO 如果老师另留有评论的话,将评论放在content里
                        """comments = new_reimb.comments
                        text = ""
                        for comment in comments.all():
                            text += comment.text
                        content += " 老师给你留言啦："
                        content += text"""

                        new_notification = notification_create(receiver, request.user, 
                                                               typename,
                                                               Notification.Title.VERIFY_INFORM, content, 
                                                               URL)
                        if html_display['warn_code'] == 1:
                            en_pw = hash_coder.encode(str(new_reimb.id) + '新建报销' + 
                                                        str(new_notification.id))
                            URL = "/addReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                                id=new_reimb.id, nid=new_notification.id, en_pw=en_pw)
                            URL = request.build_absolute_uri(URL)
                            new_notification.URL = URL
                            new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())

                context = notification_status_change(notification_id)  # 修改通知状态
                # 成功发送通知
                html_display['warn_code'] = 2
                html_display['warn_message'] = "报销通知已成功发送！"
                if context['warn_code'] != 2:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] += context['warn_message']
                # 微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)

                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
            elif submit == 3:  # 拒绝
                try:  # 发送给申请者的拒绝通知
                    with transaction.atomic():
                        new_reimb.status = Reimbursement.ReimburseStatus.CANCELED
                        new_reimb.save()
                        content = "很遗憾，报销申请未通过！"
                        receiver = new_reimb.pos  # 通知接收者
                        URL = "/notifications/"
                        URL = request.build_absolute_uri(URL)

                        # TODO 如果老师另留有评论的话,将评论放在content里
                        """comments = new_reimb.comments
                        text = ""
                        for comment in comments.all():
                            text += comment.text
                        content += " 老师给你留言啦："
                        content += text"""

                        new_notification = notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                            Notification.Title.VERIFY_INFORM, content, URL)
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())

                context = notification_status_change(notification_id)
                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "通知已成功发送！"
                if context['warn_code'] != 0:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = context['warn_message']
                # 微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)

                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
            else:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "系统出现问题，请联系管理员"
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))

    # 以下前端展示
    comments = new_reimb.comments.order_by('time')  # 加载评论
    html_display['activity_title'] = new_reimb.activity.title
    html_display['amount'] = new_reimb.amount  # 报销金额
    html_display['message'] = new_reimb.message  # 备注信息
    html_display['oname'] = new_reimb.pos.organization.oname  # 组织姓名
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "报销审核"
    bar_display["navbar_name"] = "报销审核"
    return render(request, "reimbursement_comment.html", locals())
