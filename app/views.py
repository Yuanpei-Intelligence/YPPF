from app.models import NewPosition
from threading import local
from django.dispatch.dispatcher import NO_RECEIVERS, receiver
from django.template.defaulttags import register
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    OrganizationType,
    Position,
    ModifyPosition,
    Activity,
    TransferRecord,
    Participant,
    Notification,
    NewOrganization,
    Comment,
    CommentPhoto,
    YQPointDistribute,
    Reimbursement,
)
from django.db.models import Max
import app.utils as utils
from app.forms import UserForm
from app.utils import url_check, check_cross_site, get_person_or_org
from app.activity_utils import (
    create_activity,
    modify_activity,
    accept_activity,
    applyActivity,
    cancel_activity,
    withdraw_activity,
    ActivityException,
)
from app.position_utils import(
    update_pos_application,
)
from app.wechat_send import publish_notification
from boottest import local_dict
from boottest.hasher import MyMD5PasswordHasher, MySHA256Hasher
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.contrib import auth, messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
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
                org = Organization.objects.get(oname=username)  # 如果get不到，就是账号不存在了
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
                    return redirect(
                        "/welcome/?warn_code={}&warn_message={}".format(
                            html_display["warn_code"], html_display["warn_message"]
                        )
                    )
                if not arg_origin.startswith("http"):  # 非外部链接，合法性已经检查过
                    return redirect(arg_origin)  # 不需要加密验证
                d = datetime.utcnow()
                t = mktime(datetime.timetuple(d))
                timeStamp = str(int(t))
                en_pw = hash_coder.encode(username + timeStamp)
                try:
                    userinfo = NaturalPerson.objects.get(person_id__username=username)
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
                valid, user_type, html_display = utils.check_user_type(request.user)
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
                return redirect(
                    "/welcome/?warn_code={}&warn_message={}".format(
                        html_display["warn_code"], html_display["warn_message"]
                    )
                )

            d = datetime.utcnow()
            t = mktime(datetime.timetuple(d))
            timeStamp = str(int(t))
            print("utc time: ", d)
            print(timeStamp)
            username = request.session["username"]
            en_pw = hash_coder.encode(username + timeStamp)
            return redirect(
                arg_origin + f"?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}"
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

            append_url = "" if ("?" not in full_path) else "?" + full_path.split("?")[1]
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

        # ----------------------------------- 组织卡片 ----------------------------------- #

        person_poss = Position.objects.activated().filter(Q(person=person))
        person_orgs = Organization.objects.filter(
            id__in=person_poss.values("org")
        )  # ta属于的组织
        oneself_orgs = (
            [oneself]
            if user_type == "Organization"
            else Position.objects.activated().filter(
                Q(person=oneself) & Q(show_post=True)
            )
        )
        oneself_orgs_id = oneself_orgs.values("id")  # 自己的组织

        # 管理的组织
        person_owned_poss = person_poss.filter(pos=0, status=Position.Status.INSERVICE)
        person_owned_orgs = person_orgs.filter(
            id__in=person_owned_poss.values("org")
        )  # ta管理的组织
        person_owned_orgs_ava = [
            utils.get_user_ava(org, "organization") for org in person_owned_orgs
        ]
        person_owned_orgs_pos = [
            person_owned_poss.get(org=org).pos for org in person_owned_orgs
        ]  # ta在组织中的职位
        person_owned_orgs_pos = [
            org.otype.get_name(pos)
            for pos, org in zip(person_owned_orgs_pos, person_owned_orgs)
        ]  # ta在组织中的职位
        html_display["owned_orgs_info"] = (
                list(zip(person_owned_orgs, person_owned_orgs_ava, person_owned_orgs_pos))
                or None
        )

        # 属于的组织
        person_joined_poss = person_poss.filter(~Q(pos=0) & Q(show_post=True))
        person_joined_orgs = person_orgs.filter(
            id__in=person_joined_poss.values("org")
        )  # ta属于的组织
        person_joined_orgs_ava = [
            utils.get_user_ava(org, "organization") for org in person_joined_orgs
        ]
        person_joined_orgs_pos = [
            person_joined_poss.get(org=org).pos for org in person_joined_orgs
        ]  # ta在组织中的职位
        person_joined_orgs_pos = [
            org.otype.get_name(pos)
            for pos, org in zip(person_joined_orgs_pos, person_joined_orgs)
        ]  # ta在组织中的职位
        person_joined_orgs_same = [
            id in oneself_orgs_id for id in person_joined_poss.values("org")
        ]
        html_display["joined_orgs_info"] = (
                list(
                    zip(
                        person_joined_orgs,
                        person_joined_orgs_ava,
                        person_joined_orgs_pos,
                        person_joined_orgs_same,
                    )
                )
                or None
        )

        # 隐藏的组织
        person_hidden_poss = person_poss.filter(show_post=False)
        person_hidden_orgs = person_orgs.filter(
            id__in=person_hidden_poss.values("org")
        )  # ta隐藏的组织
        person_hidden_orgs_ava = [
            utils.get_user_ava(org, "organization") for org in person_hidden_orgs
        ]
        person_hidden_orgs_pos = [
            person_hidden_poss.get(org=org).pos for org in person_hidden_orgs
        ]  # ta在组织中的职位
        person_hidden_orgs_status = [
            person_hidden_poss.get(org=org).status for org in person_hidden_orgs
        ]  # ta职位的状态
        html_display["hidden_orgs_info"] = (
                list(
                    zip(
                        person_hidden_orgs,
                        person_hidden_orgs_ava,
                        person_hidden_orgs_pos,
                        person_hidden_orgs_status,
                    )
                )
                or None
        )

        # ----------------------------------- 活动卡片 ----------------------------------- #

        participants = Participant.objects.filter(person_id=person.id)
        activities = Activity.objects.filter(
            Q(id__in=participants.values("activity_id")),
            ~Q(status=Activity.Status.CANCELED),
        )
        activities_start = [
            activity.start.strftime("%m月%d日 %H:%M") for activity in activities
        ]
        activities_end = [
            activity.end.strftime("%m月%d日 %H:%M") for activity in activities
        ]
        if user_type == "Person":
            activities_me = Participant.objects.filter(person_id=person.id).values(
                "activity_id"
            )
            activity_is_same = [
                activity in activities_me
                for activity in participants.values("activity_id")
            ]
        else:
            activities_me = activities.filter(organization_id=oneself.id).values("id")
            activities_me = [activity["id"] for activity in activities_me]
            activity_is_same = [
                activity["activity_id"] in activities_me
                for activity in participants.values("activity_id")
            ]
        participate_status_list = participants.values("status")
        participate_status_list = [info["status"] for info in participate_status_list]
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
        activity_color_list = [status_color[activity.status] for activity in activities]
        attend_color_list = [status_color[status] for status in participate_status_list]
        activity_info = list(
            zip(
                activities,
                activities_start,
                activities_end,
                participate_status_list,
                activity_is_same,
                activity_color_list,
                attend_color_list,
            )
        )
        activity_info.sort(key=lambda a: a[0].start, reverse=True)
        html_display["activity_info"] = list(activity_info) or None

        # 警告呈现信息

        try:
            html_display["warn_code"] = int(
                request.GET.get("warn_code", 0)
            )  # 是否有来自外部的消息
        except:
            return redirect("/welcome/")
        html_display["warn_message"] = request.GET.get("warn_message", "")  # 提醒的具体内容

        modpw_status = request.GET.get("modinfo", None)
        if modpw_status is not None and modpw_status == "success":
            html_display["warn_code"] = 2
            html_display["warn_message"] = "修改个人信息成功!"

        # 存储被查询人的信息
        context = dict()

        context["person"] = person

        context["title"] = "我" if is_myself else "Ta"

        context["avatar_path"] = utils.get_user_ava(person, "Person")
        context["wallpaper_path"] = utils.get_user_wallpaper(person)

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display
        bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="个人主页")
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
        append_url = "" if ("?" not in full_path) else "?" + full_path.split("?")[1]

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
        dictmp["endbefore"] = act.start - timedelta(hours=prepare_times[act.endbefore])
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
        dictmp["endbefore"] = act.start - timedelta(hours=prepare_times[act.endbefore])
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

            member["avatar_path"] = utils.get_user_ava(member["person"], "Person")

            member_list.append(member)

    try:
        html_display["warn_code"] = int(request.GET.get("warn_code", 0))  # 是否有来自外部的消息
    except:
        return redirect("/welcome/")
    html_display["warn_message"] = request.GET.get("warn_message", "")  # 提醒的具体内容

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
        html_display["warn_code"] = int(request.GET.get("warn_code", 0))  # 是否有来自外部的消息
    except:
        return redirect("/welcome/")
    html_display["warn_message"] = request.GET.get("warn_message", "")  # 提醒的具体内容

    nowtime = datetime.now()
    # 今天第一次访问 welcome 界面，积分加 0.5
    if is_person:
        with transaction.atomic():
            np = NaturalPerson.objects.select_for_update().get(person_id=request.user)
            if np.last_time_login is None or np.last_time_login.date != nowtime.date:
                np.last_time_login = nowtime
                np.bonusPoint += 0.5
                np.save()

    # 今天开始进行的活动,且不展示结束的活动。按开始时间由近到远排序
    today_activity_list = (
        Activity.objects.activated()
            .filter(
            Q(start__year=nowtime.year)
            & Q(start__month=nowtime.month)
            & Q(start__day=nowtime.day)
        )
            .filter(
            status__in=[
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING,
            ]
        )
            .order_by("start")
    )
    # 今天可以报名的活动。按截止时间由近到远排序
    prepare_times = Activity.EndBeforeHours.prepare_times
    signup_rec = Activity.objects.activated().filter(status=Activity.Status.APPLYING)
    today_signup_list = []
    for act in signup_rec:
        dictmp = {}
        dictmp["endbefore"] = act.start - timedelta(hours=prepare_times[act.endbefore])
        dictmp["act"] = act
        today_signup_list.append(dictmp)
    today_signup_list.sort(key=lambda x: x["endbefore"])

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Welcome Page"
    bar_display["navbar_name"] = "元培生活"

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

    # 补充网页呈现所需信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Account Setting"
    bar_display["navbar_name"] = "账户设置"
    bar_display["help_message"] = local_dict["help_message"]["账户设置"]

    if user_type == "Person":
        info = NaturalPerson.objects.filter(person_id=user)
        userinfo = info.values()[0]

        useroj = NaturalPerson.objects.get(person_id=user)

        former_wallpaper = utils.get_user_wallpaper(me)

        # print(json.loads(request.body.decode("utf-8")))
        if request.method == "POST" and request.POST:
        
            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(request, user_type)
            attr_check_list = [attr for attr in attr_dict.keys() if attr  not in ['gender','ava','wallpaper']]
            if html_display['warn_code'] == 1:
                return render(request, "person_account_setting.html", locals())

            expr = bool(attr_dict['ava'] or attr_dict['wallpaper'] or (attr_dict['gender'] != useroj.get_gender_display()))
            expr += bool(sum(
                [(getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "") for attr in attr_check_list]))
            expr += bool(sum([getattr(useroj, show_attr) != show_dict[show_attr]
                         for show_attr in show_dict.keys()]))

            if attr_dict['gender'] != useroj.gender:
                useroj.gender = NaturalPerson.Gender.MALE if attr_dict['gender'] == '男' else NaturalPerson.Gender.FEMALE
            for attr in attr_check_list:
                if getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "":
                    setattr(useroj, attr, attr_dict[attr])
            for show_attr in show_dict.keys():
                if getattr(useroj, show_attr) != show_dict[show_attr]:
                    setattr(useroj, show_attr, show_dict[show_attr])
            if 'ava' in attr_dict.keys() and attr_dict['ava'] is not None:
                useroj.avatar =  attr_dict['ava']
            if 'wallpaper' in attr_dict.keys() and attr_dict['wallpaper'] is not None:
                useroj.wallpaper = attr_dict['wallpaper']
            if expr >= 1:
                useroj.save()
                upload_state = True
                return redirect("/stuinfo/?modinfo=success")
            # else: 没有更新

        return render(request, "person_account_setting.html", locals())

    else:
        info = Organization.objects.filter(organization_id=user)
        userinfo = info.values()[0]

        useroj = Organization.objects.get(organization_id=user)

        if request.method == "POST" and request.POST:

            ava = request.FILES.get("avatar")
            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(request, user_type)
            attr_check_list = [attr for attr in attr_dict.keys()]
            if html_display['warn_code'] == 1:
                return render(request, "person_account_setting.html", locals())
                
            expr = bool(ava)
            expr += bool(sum(
                [(getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "") for attr in attr_check_list]))

            for attr in attr_check_list:
                if getattr(useroj, attr) != attr_dict[attr] and attr_dict[attr] != "":
                    setattr(useroj, attr, attr_dict[attr])
            if ava is None:
                pass
            else:
                useroj.avatar = ava
            useroj.save()
            avatar_path = settings.MEDIA_URL + str(ava)
            if expr >= 1:
                upload_state = True
                return redirect("/orginfo/?modinfo=success")
            # else: 没有更新

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
                    err_message = (
                            "您没有设置邮箱，请联系管理员" + "或发送姓名、学号和常用邮箱至gypjwb@pku.edu.cn进行修改"
                    )  # TODO:记得填
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
                            "有效)</span></p>"
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
                        response = requests.post(email_url, post_data, timeout=6)
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
    """
        可能在三种情况进入这个页面：首次登陆；忘记密码；或者常规的修改密码。
        在忘记密码时，可以允许不输入旧的密码
        在首次登陆时，现在写的也可以不输入旧的密码（我还没想好这样合不合适）
            以上两种情况都可以直接进行密码修改
        常规修改要审核旧的密码
    """
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
                    username=username, password=oldpassword
                )  # 验证旧密码是否正确
            if userauth:  # 可以修改
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
    context = utils.get_sidebar_and_navbar(user, bar_display=context)
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
            lis[-1]["obj_url"] = "/stuinfo/" + lis[-1]["obj"] + "+" + str(obj_user.id)
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
            record_id, action = post_args.split("+")[0], post_args.split("+")[1]
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
    issued_set = issued_send_set.union(issued_recv_set).order_by("-finish_time")

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
        valid, user_type, html_display = utils.check_user_type(request.user)
        assert valid
    except:
        return redirect("/welcome/")

    me = utils.get_person_or_org(request.user, user_type)

    # 下面这些都是展示前端页面要用的
    title = activity.title
    org = activity.organization_id
    org_name = org.oname
    org_avatar_path = utils.get_user_ava(org, "Organization")
    org_type = OrganizationType.objects.get(otype_id=org.otype_id).otype_name
    start_time = activity.start
    end_time = activity.end
    prepare_times = Activity.EndBeforeHours.prepare_times
    apply_deadline = activity.apply_end
    introduction = activity.introduction
    show_url = True  # 前端使用量
    aURL = activity.URL
    if aURL is None:
        show_url = False
    aQRcode = activity.QRcode
    bidding = activity.bidding
    price = activity.YQPoint
    from_student = activity.source == Activity.YQPointSource.STUDENT
    current_participants = activity.current_participants
    status = activity.status
    capacity = activity.capacity
    if capacity == -1 or capacity == 10000:
        capacity = "INF"
    if activity.examine_teacher == me:
        examine = True
    # person 表示是否是个人而非组织
    person = False
    if user_type == "Person":
        """
        老师能否报名活动？
        if me.identity == NaturalPerson.Identity.STUDENT:
            person = True
        """
        person = True
        try:
            participant = Participant.objects.get(activity_id=activity, person_id=me.id)
            # pStatus 是参与状态
            pStatus = participant.status
        except:
            pStatus = "无记录"
        if pStatus == "放弃":
            pStatus = "无记录"
    # ownership 表示是否是这个活动的所有组织
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
    # 处理 post 请求
    # try:
    option = request.POST.get("option")
    if option == "cancel":
        # try:
        assert activity.status != Activity.Status.END
        assert activity.status != Activity.Status.CANCELED
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)
            cancel_activity(request, activity)
            return redirect(f"/viewActivity/{aid}")
        """
        except ActivityError as e:
            html_display["warn_code"] = 1
            html_display["warn_message"] = str(e)
            return render(request, "activity_info.html", locals())
        except:
            redirect("/welcome/")
        """

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
            return redirect(f"/addActivities/?edit=True&aid={aid}")
        else:
            html_display["warn_code"] = 1
            html_display["warn_message"] = f"活动状态为{activity.status}, 不能修改。"
            return render(request, "activity_info.html", locals())

    elif option == "apply":
        # try:
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=int(aid))
            applyActivity(request, activity)
            return redirect(f"/viewActivity/{aid}")
        """
        except ActivityError as e:
            html_display["warn_message"] = str(e)
        except:
            redirect('/welcome/')
        """
        return render(request, "activity_info.html", locals())

    elif option == "quit":
        # try:
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)
            assert (
                    activity.status == Activity.Status.APPLYING
                    or activity.status == Activity.Status.WAITING
            )
            withdraw_activity(request, activity)
            return redirect(f"/viewActivity/{aid}")
        """
        except ActivityError as e:
            html_display["warn_message"] = str(e)
        except:
            return redirect('/welcome/')
        """

        return render(request, "activity_info.html", locals())

    elif option == "payment":
        return redirect("/addReimbursement/")

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
                lambda paticipant: map(lambda key: paticipant[key], fields),
                participants,
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
            checkin_url = parse.urljoin(origin_url, checkin_url)  # require full path

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


该函数处理 GET, POST 两种请求

1. 使用 GET 方法时，如果存在 edit=True 参数，展示修改活动的界面，否则展示创建活动的界面。
    a. 创建活动的界面，placeholder 为 prompt
    b. 编辑活动的界面，表单的 placeholder 会被修改为活动的旧值。并且添加两个 hidden input，分别提交 edit=True 和活动的 id

2. 当请求方法为 POST 时，处理请求并修改数据库，如果没有问题，跳转到展示活动信息的界面
    a. 页面检查逻辑主要放到前端，出现不合法输入跳转到 welcome 界面
    b. 存在 edit 和 aid 参数时，为编辑操作。input 并不包含 model 所有 field 的数据，只对其中出现的进行修改

P.S. 
    编辑活动的页面，直接把 value 设成旧值而不是 placeholder 代码会简单很多。
    只是觉得 placeholder 好看很多所以没用 value。
    用 placeholder 在提交表单时会出现很多空值，check 函数需要特判，导致代码很臃肿......

    一种可行的修改方式是表单提交的时候用 JS 把 value 的值全换成 placeholder 内的值。
    好像也不是很优雅。
    时间那里的检查比较复杂，表单提交前使用 JS 进行了修改

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

    # 处理 POST 请求
    if request.method == "POST" and request.POST:

        # 看是否是 edit，如果是做一些检查
        edit = request.POST.get("edit")
        if edit is not None:

            # try:
            aid = int(request.POST["aid"])
            assert edit == "True"
            # 只能修改自己的活动
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(id=aid)
                org = get_person_or_org(request.user, "Organization")
                assert activity.organization_id == org
                modify_activity(request, activity)
            return redirect(f"/viewActivity/{activity.id}")
            """
            except:
                return redirect("/welcome/")
            """
        else:
            """
            # DEBUG:
            aid = create_activity(request)
            return redirect(f"/viewActivity/{aid}")
            """
            try:
                aid = create_activity(request)
                return redirect(f"/viewActivity/{aid}")
            except:
                return redirect("/welcome/")

    # 处理 GET 请求
    elif request.method == "GET":

        edit = request.GET.get("edit")
        if edit is None or edit != "True":
            edit = False
            bar_display["title_name"] = "新建活动"
            bar_display["narbar_name"] = "新建活动"
        else:
            # 编辑状态下，填写 placeholder 为旧值
            edit = True
            commentable = True
            try:
                aid = int(request.GET["aid"])
                activity = Activity.objects.get(id=aid)
                org = get_person_or_org(request.user, "Organization")
                assert activity.organization_id == org
                if activity.status == Activity.Status.REVIEWING:
                    pass
                elif (
                        activity.status == Activity.Status.APPLYING
                        or activity.status == Activity.Status.WAITING
                ):
                    accepted = True
                    assert datetime.now() + timedelta(hours=1) < activity.start
                else:
                    raise ValueError
            except:
                return redirect("/welcome/")

            title = activity.title
            budget = activity.budget
            location = activity.location
            start = activity.start.strftime("%m/%d/%Y %H:%M %p")
            end = activity.end.strftime("%m/%d/%Y %H:%M %p")
            apply_end = activity.apply_end.strftime("%m/%d/%Y %H:%M %p")
            introduction = activity.introduction
            url = activity.URL
            endbefore = activity.endbefore
            bidding = activity.bidding
            amount = activity.YQPoint
            signscheme = "先到先得"
            if bidding:
                signscheme = "投点参与"
            capacity = activity.capacity
            yq_source = "向学生收取"
            if activity.source == Activity.YQPointSource.COLLEGE:
                yq_source = "向学院申请"
            no_limit = False
            if capacity == 10000:
                no_limit = True
            examine_teacher = activity.examine_teacher.name
            bar_display["title_name"] = "修改活动"
            bar_display["narbar_name"] = "修改活动"
            status = activity.status
            if status != Activity.Status.REVIEWING:
                accepted = True

        html_display["today"] = datetime.now().strftime("%Y-%m-%d")
        bar_display = utils.get_sidebar_and_navbar(request.user)

        return render(request, "activity_add.html", locals())

    else:
        return redirect("/welcome/")


@login_required(redirect_field_name="origin")
def examineActivity(request, aid):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if not valid:
        return redirect("/index/")
    if user_type == "Organization":
        return redirect("/welcome/")  # test
    me = utils.get_person_or_org(request.user)
    html_display["is_myself"] = True
    bar_display = utils.get_sidebar_and_navbar(request.user)

    if request.method == "GET":
        try:
            activity = Activity.objects.get(id=int(aid))
            assert activity.examine_teacher == me
        except:
            return redirect("/welcome/")

        examine = True

        title = activity.title
        budget = activity.budget
        location = activity.location
        apply_end = activity.apply_end.strftime("%m/%d/%Y %H:%M %p")
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
        yq_source = "向学生收取"
        if activity.source == Activity.YQPointSource.COLLEGE:
            yq_source = "向学院申请"
        no_limit = False
        if capacity == 10000:
            no_limit = True
        examine_teacher = activity.examine_teacher.name
        bar_display["title_name"] = "审查活动"
        bar_display["narbar_name"] = "审查活动"

        html_display["today"] = datetime.now().strftime("%Y-%m-%d")
        bar_display = utils.get_sidebar_and_navbar(request.user)

        status = activity.status
        if activity.status != Activity.Status.REVIEWING:
            no_review = True

        return render(request, "activity_add.html", locals())

    elif request.method == "POST" and request.POST:
        # try:
        assert request.POST["examine"] == "True"
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(
                id=int(request.POST["aid"])
            )
            assert activity.status == Activity.Status.REVIEWING
            assert activity.examine_teacher == me
            accept_activity(request, activity)
        return redirect(f"/examineActivity/{request.POST['aid']}")
        """
        except:
            return redirect("/welcome/")
        """

    else:
        return redirect("/welcome/")


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
        org.organization_id.username
        for org in org_list
        if org.organization_id.username not in unsubscribe_list
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
                    Organization.objects.get(organization_id__username=params["id"])
                )
            else:
                me.unsubscribe_list.add(
                    Organization.objects.get(organization_id__username=params["id"])
                )
        elif "otype" in params.keys():
            unsubscribed_list = me.unsubscribe_list.filter(
                otype__otype_id=params["otype"]
            )
            org_list = Organization.objects.filter(otype__otype_id=params["otype"])
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
        apply_type, _ = Position.objects.create_application(
            me, org, apply_type, apply_pos)
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
        issued_status = Q(apply_status=Position.ApplyStatus.PASS) | Q(
            apply_status=Position.ApplyStatus.REJECT
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
            application = Position.objects.select_for_update().get(id=params["id"])
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

        # 查找已处理的该条人事对应的通知信息
        done_notification = Notification.objects.activated().get(
            typename=Notification.Type.NEEDDO,
            sender=application.person.person_id,
            receiver=me.organization_id,
        )

        notification_status_change(done_notification.id)

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
            lis[-1]["finish_time"] = notification.finish_time.strftime("%m/%d %H:%M")

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


def notification_status_change(notification_or_id, to_status=None):
    """
    调用该函数以完成一项通知。对于知晓类通知，在接收到用户点击按钮后的post表单，该函数会被调用。
    对于需要完成的待处理通知，需要在对应的事务结束判断处，调用该函数。
    notification_id是notification的主键:id
    to_status是希望这条notification转变为的状态，包括
        DONE = (0, "已处理")
        UNDONE = (1, "待处理")
        DELETE = (2, "已删除")
    若不给to_status传参，默认为状态翻转：已处理<->未处理
    """
    context = dict()
    context["warn_code"] = 1
    context["warn_message"] = "在修改通知状态的过程中发生错误，请联系管理员！"

    if isinstance(notification_or_id, Notification):
        notification_id = notification_or_id.id
    else:
        notification_id = notification_or_id

    if to_status is None:  # 表示默认的状态翻转操作
        if isinstance(notification_or_id, Notification):
            now_status = notification_or_id.status
        else:
            try:
                notification = Notification.objects.get(id=notification_id)
                now_status = notification.status
            except:
                context["warn_message"] = "该通知不存在！"
                return context
        if now_status == Notification.Status.DONE:
            to_status = Notification.Status.UNDONE
        elif now_status == Notification.Status.UNDONE:
            to_status = Notification.Status.DONE
        else:
            to_status = Notification.Status.DELETE
            # context["warn_message"] = "已删除的通知无法翻转状态！"
            # return context    # 暂时允许

    with transaction.atomic():
        try:
            notification = Notification.objects.select_for_update().get(
                id=notification_id
            )
        except:
            context["warn_message"] = "该通知不存在！"
            return context
        if notification.status == to_status:
            context["warn_code"] = 2
            context["warn_message"] = "通知状态无需改变！"
            return context
        if (
                notification.status == Notification.Status.DELETE
                and notification.status != to_status
        ):
            context["warn_code"] = 2
            context["warn_message"] = "不能修改已删除的通知！"
            return context
        if to_status == Notification.Status.DONE:
            notification.status = Notification.Status.DONE
            notification.finish_time = datetime.now()  # 通知完成时间
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "您已成功阅读一条通知！"
        elif to_status == Notification.Status.UNDONE:
            notification.status = Notification.Status.UNDONE
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "成功设置一条通知为未读！"
        elif to_status == Notification.Status.DELETE:
            notification.status = Notification.Status.DELETE
            notification.save()
            context["warn_code"] = 2
            context["warn_message"] = "成功删除一条通知！"
        return context


def notification_create(
        receiver,
        sender,
        typename,
        title,
        content,
        URL=None,
        relate_TransferRecord=None,
        relate_instance=None,
        *,
        publish_to_wechat=False,
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
        relate_instance=relate_instance,
    )
    if publish_to_wechat == True:
        publish_notification(notification)
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
        if "cancel" in post_args:
            notification_id = int(post_args.split("+")[0])
            notification_status_change(notification_id, Notification.Status.DELETE)
            html_display["warn_code"] = 2  # success
            html_display["warn_message"] = "您已成功删除一条通知！"
        else:
            notification_id = post_args
            context = notification_status_change(notification_id)
            html_display["warn_code"] = context["warn_code"]
            html_display["warn_message"] = context["warn_message"]
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    done_set = Notification.objects.activated().filter(
        receiver=request.user, status=Notification.Status.DONE
    )

    undone_set = Notification.objects.activated().filter(
        receiver=request.user, status=Notification.Status.UNDONE
    )

    done_list = notification2Display(
        list(done_set.union(done_set).order_by("-finish_time"))
    )
    undone_list = notification2Display(
        list(undone_set.union(undone_set).order_by("-start_time"))
    )

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="通知信箱")
    return render(request, "notifications.html", locals())


# 新建评论，


def addComment(request, comment_base, receiver=None):
    """
    传入POST得到的request和与评论相关联的实例即可
    返回值为1代表失败，返回2代表新建评论成功
    """
    context = dict()
    context["warn_code"] = 2
    context["warn_message"] = ""
    if request.POST.get("comment_submit") is not None:  # 新建评论信息，并保存
        text = str(request.POST.get("comment"))
        # 检查图片合法性
        comment_images = request.FILES.getlist('comment_images')
        if text == "" and comment_images == []:
            context['warn_code'] = 1
            context['warn_message'] = "评论内容为空，无法评论！"
            return context
        if len(comment_images) > 0:
            for comment_image in comment_images:
                if utils.if_image(comment_image) == False:
                    context["warn_code"] = 1
                    context["warn_message"] = "上传的附件只支持图片格式。"
                    return context
        try:
            with transaction.atomic():
                new_comment = Comment.objects.create(
                    commentbase=comment_base, commentator=request.user, text=text
                )
                if len(comment_images) > 0:
                    for comment_image in comment_images:
                        CommentPhoto.objects.create(
                            image=comment_image, comment=new_comment
                        )
                comment_base.save()  # 每次save都会更新修改时间
        except:
            context["warn_code"] = 1
            context["warn_message"] = "评论失败，请联系管理员。"
        context["new_comment"] = new_comment
    return context


def showComment(commentbase):
    comments = commentbase.comments.order_by("time")
    for comment in comments:
        commentator = get_person_or_org(comment.commentator)
        if comment.commentator.username[:2] == "zz":
            comment.ava = utils.get_user_ava(comment.commentator, "Organization")
            comment.URL = "/orginfo/{name}".format(name=commentator.oname)
            comment.commentator_name = commentator.oname
        else:
            comment.ava = utils.get_user_ava(comment.commentator, "Person")
            comment.URL = "/stuinfo/{name}".format(name=commentator.name)
            comment.commentator_name = commentator.name
        comment.len = len(comment.comment_photos.all())
    comments.len = len(comments.all())
    return comments


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def showNewOrganization(request):
    """
    YWolfeee: modefied on Aug 24 1:33 a.m. UTC-8
    新建组织的聚合界面
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        html_display["warn_code"] = 1
        html_display["warn_code"] = "请不要使用组织账号申请新组织！"
        return redirect(
            "/welcome/"
            + "?warn_code={}&warn_message={}".format(
                html_display["warn_code"], html_display["warn_message"]
            )
        )

    me = utils.get_person_or_org(request.user, user_type)

    # 拉取我负责管理申请的组织，这部分由我审核
    charge_org = NewOrganization.objects.filter(otype__in=me.incharge.all())

    # 拉去由我发起的申请，这部分等待审核
    applied_org = NewOrganization.objects.filter(pos=request.user)

    # 排序整合，用于前端呈现
    shown_instances = charge_org.union(applied_org).order_by("-modify_time", "-time")

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="新组织申请")
    return render(request, "neworganization_show.html", locals())


# 新建组织 or 修改新建组织信息
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def addOrganization(request):
    """
    新建组织，首先是由check_neworg_request()检查输入的合法性，再存储申请信息到NewOrganization的一个实例中
    之后便是创建给对应审核老师的通知
    """
    TERMINATE_STATUSES = [
        NewOrganization.NewOrgStatus.CONFIRMED,
        NewOrganization.NewOrgStatus.CANCELED,
        NewOrganization.NewOrgStatus.REFUSED,
    ]
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        return redirect("/welcome/")  # test

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    former_img = utils.get_user_ava(None, "Organization")
    present = 0  # 前端需要，1代表能展示，0代表初始申请
    commentable = 0  # 前端需要，表示能否评论。
    edit = 0  # 前端需要，表示第一次申请后修改
    notification_id = -1
    # 0可以新建，一个可以查看，如果正在申请中，则可以新建评论，可以取消。两个表示的话，啥都可以。
    if (
            request.GET.get("neworg_id") is not None
            and request.GET.get("notifi_id") is None
    ):
        # 不是初次申请，而是修改或访问记录
        # 只要id正确，就能显示
        # 是否能够取消,
        # 检查是否为本人，
        try:
            id = int(request.GET.get("neworg_id"))  # 新建组织的ID
            preorg = NewOrganization.objects.get(id=id)
            notification_id = request.GET.get("notifi_id", -1)
            if notification_id != -1:
                # 说明是通过信箱进入的，检查加密
                notification_id = int(notification_id)  # 通知ID
                en_pw = str(request.GET.get("enpw"))
                if (
                        hash_coder.verify(str(id) + "新建组织" + str(notification_id), en_pw)
                        == False
                ):
                    raise Exception("新建组织加密验证未通过")
                notification = Notification.objects.get(id=notification_id)
                if notification.status == Notification.Status.DELETE:
                    raise Exception("不能通过已删除的通知查看组织申请信息！")
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "该URL被篡改，请输入正确的URL地址"
            return redirect(
                "/notifications/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        if preorg.pos != request.user:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有权力查看此通知"
            return redirect(
                "/notifications/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        if preorg.status == NewOrganization.NewOrgStatus.PENDING:  # 正在申请中，可以评论。
            commentable = 1  # 可以评论
            edit = 1  # 能展示也能修改
        present = 1  # 能展示
    if (
            request.GET.get("neworg_id") is not None
            and request.GET.get("notifi_id") is not None
    ):
        try:
            id = int(request.GET.get("neworg_id"))  # 新建组织ID
            notification_id = int(request.GET.get("notifi_id"))  # 通知ID
            en_pw = str(request.GET.get("enpw"))
            if (
                    hash_coder.verify(str(id) + "新建组织" + str(notification_id), en_pw)
                    == False
            ):
                html_display["warn_code"] = 1
                html_display["warn_message"] = "该URL被篡改，请输入正确的URL地址"
                return redirect(
                    "/notifications/"
                    + "?warn_code={}&warn_message={}".format(
                        html_display["warn_code"], html_display["warn_message"]
                    )
                )
            preorg = NewOrganization.objects.get(id=id)
            notification = Notification.objects.get(id=notification_id)
        except:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "获取申请信息失败，请联系管理员。"
            return redirect(
                "/notifications/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        if preorg.status == NewOrganization.NewOrgStatus.PENDING:  # 正在申请中，可以评论。
            commentable = 1  # 可以评论
            edit = 1
        present = 1

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织"
    bar_display["navbar_name"] = "新建组织"

    if present:  # 展示信息
        html_display['oname'] = preorg.oname
        html_display['otype_id'] = preorg.otype.otype_id  #
        html_display['otype_name'] = preorg.otype.otype_name  #
        html_display['pos'] = preorg.pos  # 组织负责人的呈现 TODO:主页可点击头像 学号+姓名
        html_display['introduction'] = preorg.introduction  # 组织介绍
        html_display['application'] = preorg.application  # 组织申请信息
        html_display['status'] = preorg.status  # 状态名字
        org_avatar_path = utils.get_user_ava(preorg, "Organization")  # 组织头像
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织"
    bar_display["navbar_name"] = "新建组织"

    org_types = OrganizationType.objects.order_by("-otype_id").all()  # 当前组织类型，前端展示需要

    if request.method == "POST" and request.POST:
        if request.POST.get("comment_submit") is not None:  # 新建评论信息，并保存
            context = addComment(request, preorg)
            if context['warn_code'] == 1:
                html_display['warn_code'] = 1
                html_display['warn_message'] = context['warn_message']
            else:
                try:  # 发送给评论通知
                    with transaction.atomic():
                        text = str(context["new_comment"].text)
                        if len(text) >= 32:
                            text = text[:31] + "……"
                        content = "“{oname}”{otype_name}的新建组织申请有了新的评论：“{text}” ".format(
                            oname=preorg.oname,
                            otype_name=preorg.otype.otype_name,
                            text=text,
                        )
                        Auditor = preorg.otype.incharge.person_id  # 审核老师
                        URL = ""
                        new_notification = notification_create(
                            Auditor,
                            request.user,
                            Notification.Type.NEEDREAD,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )
                        en_pw = hash_coder.encode(
                            str(preorg.id) + "新建组织" + str(new_notification.id)
                        )
                        URL = "/auditOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=preorg.id, nid=new_notification.id, en_pw=en_pw
                        )
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建发送给审核老师的评论通知失败。请联系管理员！"
                    return render(request, "organization_add.html", locals())
                # 微信通知
                publish_notification(new_notification)
                html_display['warn_code'] = 2
                html_display['warn_message'] = "评论成功！"
        else:  # 取消+新建+修改
            # 取消
            need_cancel = int(request.POST.get('cancel_submit', -1))
            if need_cancel == 1:  # 1代表取消
                if edit:
                    with transaction.atomic():  # 修改状态为取消
                        preorg.status = NewOrganization.NewOrgStatus.CANCELED
                        preorg.save()
                    try:
                        with transaction.atomic():
                            content = "“{oname}”的新建申请已取消".format(oname=preorg.oname)
                            # 在local_json.json新增审批人员信息,暂定为YPadmin
                            Auditor = preorg.otype.incharge.person_id  # 审核老师
                            URL = ""
                            new_notification = notification_create(
                                Auditor,
                                request.user,
                                Notification.Type.NEEDREAD,
                                Notification.Title.VERIFY_INFORM,
                                content,
                                URL,
                            )
                            en_pw = hash_coder.encode(
                                str(preorg.id) + "新建组织" + str(new_notification.id)
                            )
                            URL = "/auditOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                                id=preorg.id, nid=new_notification.id, en_pw=en_pw
                            )
                            # URL = request.build_absolute_uri(URL)
                            new_notification.URL = URL
                            new_notification.save()
                    except:
                        html_display["warn_code"] = 1
                        html_display[
                            "warn_message"
                        ] = "创建给{auditor_name}老师的取消通知失败。请联系管理员。".format(
                            auditor_name=preorg.otype.incharge.name
                        )
                        return render(request, "organization_add.html", locals())
                    # 微信通知
                    publish_notification(new_notification)
                    # 成功新建组织申请
                    html_display["warn_code"] = 2
                    html_display["warn_message"] = "已成功取消申请！"
                    return render(request, "organization_add.html", locals())
            # 以下为修改
            # 参数合法性检查
            if edit:
                context = utils.check_neworg_request(request, preorg)  # check
            else:
                context = utils.check_neworg_request(request)  # check
            if context["warn_code"] != 0:
                html_display["warn_code"] = context["warn_code"]
                html_display["warn_message"] = "新建组织申请失败。" + context["warn_msg"]
                return render(request, "organization_add.html", locals())
            # 新建组织申请
            if edit == 0:
                try:
                    with transaction.atomic():
                        new_org = NewOrganization.objects.create(
                            oname=context["oname"],
                            otype=context["otype"],
                            pos=context["pos"],
                        )
                        new_org.introduction = context["introduction"]
                        if context["avatar"] is not None:
                            new_org.avatar = context["avatar"]
                        new_org.application = context["application"]
                        new_org.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建预备组织信息失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                try:
                    with transaction.atomic():
                        content = "新建组织申请：“{oname}”".format(oname=new_org.oname)
                        # 审核人员信息,暂定为各个otype的incharge
                        Auditor = new_org.otype.incharge.person_id  # 审核老师
                        URL = ""
                        new_notification = notification_create(
                            Auditor,
                            request.user,
                            Notification.Type.NEEDDO,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )
                        en_pw = hash_coder.encode(
                            str(new_org.id) + "新建组织" + str(new_notification.id)
                        )
                        URL = "/auditOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=new_org.id, nid=new_notification.id, en_pw=en_pw
                        )
                        # URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                publish_notification(new_notification)

                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功发送，请耐心等待{auditor_name}老师审批！" \
                    .format(auditor_name=new_org.otype.incharge.name)

            # 修改组织申请
            else:
                # 修改信息
                try:
                    with transaction.atomic():
                        preorg.oname = context["oname"]
                        preorg.otype = context["otype"]
                        preorg.introduction = context["introduction"]

                        if context["avatar"] is not None:
                            preorg.avatar = context["avatar"]
                        preorg.application = context["application"]
                        preorg.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "修改申请失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())

                # 发送通知
                try:
                    with transaction.atomic():
                        content = "新建组织“{oname}”的材料已修改，请您继续审核！".format(
                            oname=preorg.oname
                        )
                        # 审核人员信息,暂定为各个otype的incharge
                        Auditor = preorg.otype.incharge.person_id  # 审核老师
                        URL = ""
                        new_notification = notification_create(
                            Auditor,
                            request.user,
                            Notification.Type.NEEDDO,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )
                        en_pw = hash_coder.encode(
                            str(preorg.id) + "新建组织" + str(new_notification.id)
                        )
                        URL = "/auditOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=preorg.id, nid=new_notification.id, en_pw=en_pw
                        )
                        # URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "organization_add.html", locals())
                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功修改，请耐心等待{auditor_name}老师审批！" \
                    .format(auditor_name=preorg.otype.incharge.name)
                if notification_id != -1:  # 注意状态
                    context = notification_status_change(notification_id, Notification.Status.DONE)
                    if context['warn_code'] != 0:
                        html_display['warn_message'] = context['warn_message']
                # 微信通知
                publish_notification(new_notification)
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))

    if present:  # 展示信息
        comments = showComment(preorg)
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织"
    bar_display["navbar_name"] = "新建组织"
    return render(request, "organization_add.html", locals())

# 加入组织 or 修改加入组织信息
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def applyOrganization(request):

    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        return redirect("/welcome/")  # test

    me = utils.get_person_or_org(request.user, user_type)
    html_display['is_myself'] = True
    edit = 0    # 前端需要，表示第一次申请后修改
    present = 0  # 前端需要，1代表能展示，0代表初始申请
    commentable = 0 # 前端需要，表示能否评论。
    notification_id = -1
    if request.GET.get("newpos_id") is not None and request.GET.get('notifi_id') is None:
        try:
            id = int(request.GET.get('newpos_id'))  # 新建组织ID
            prepos = NewPosition.objects.get(id=id)
        except:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
            return redirect('/notifications/' +'?warn_code={}&warn_message={}'.format(
                html_display['warn_code'], html_display['warn_message']))
        if prepos.status == NewPosition.NewPosStatus.PENDING:
            commentable = 1
            edit = 1
        present = 1
    elif request.GET.get('newpos_id') is not None and request.GET.get('notifi_id') is not None:
        try:
            id = int(request.GET.get('newpos_id'))  # 新建组织ID
            notification_id = int(request.GET.get('notifi_id'))  # 通知ID
            en_pw = str(request.GET.get('enpw'))
            if hash_coder.verify(str(id) + '人事申请' + str(notification_id),
                                 en_pw) == False:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
                return redirect('/notifications/' +
                                '?warn_code={}&warn_message={}'.format(
                                    html_display['warn_code'], html_display['warn_message']))
            prepos = NewPosition.objects.get(id=id)
            notification = Notification.objects.get(id=notification_id)
        except:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
        if prepos.status == NewPosition.NewPosStatus.PENDING:  # 正在申请中，可以评论。
            commentable = 1  # 可以评论
            edit = 1
        present=1
        

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "人事申请"
    bar_display["navbar_name"] = "人事申请"
    
    if present:  # 展示信息
        comments = prepos.comments.order_by("time")
        html_display['application'] = prepos.application#组织申请信息
        html_display['status']=prepos.status #状态名字
        html_display['oname']=prepos.position.org.oname
        html_display['apply_pos']=prepos.apply_pos
        html_display['apply_type']=prepos.apply_type

    if request.method == "POST" and request.POST:
        if request.POST.get('comment_submit') is not None:  # 新建评论信息，并保存
            context = addComment(request, prepos)
            if context['warn_code'] == 1:
                html_display['warn_code'] = 1
                html_display['warn_message'] = context['warn_code']
            else:
                #TODO 评论通知的发送，wechat发送通知
                pass
        else:#取消+新建+修改
            #取消
            need_cancel=int(request.POST.get('cancel_submit',-1))
            html_display['warn_code'] = 1
            html_display['warn_message'] = "test{need_cancel}".format(need_cancel=need_cancel)
            if need_cancel == 1:                    # 1代表取消
                if edit:
                    with transaction.atomic():      # 修改状态为取消
                        prepos.status=NewPosition.NewPosStatus.CANCELED
                        prepos.save()
                    try:
                        with transaction.atomic():
                            content = "“{name}”的加入“{oname}”新建组织申请已取消".format(
                                name=prepos.position.person.name, oname=prepos.position.org.oname)
                            
                            Auditor = prepos.position.org.organization_id    #组织发送
                            URL = ""
                            new_notification = notification_create(Auditor, request.user,
                                                                   Notification.Type.NEEDREAD,
                                                                   Notification.Title.VERIFY_INFORM, content,
                                                                   URL)
                            en_pw = hash_coder.encode(str(prepos.id) + '人事变动' +
                                                      str(new_notification.id))
                            URL = "/auditPosition?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                                id=prepos.id, nid=new_notification.id, en_pw=en_pw)
                            # URL = request.build_absolute_uri(URL)
                            new_notification.URL = URL
                            new_notification.save()
                    except:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "创建给组织审核的取消通知失败。请联系管理员。"
                        return render(request, "applyOrganization.html", locals())
                        # 微信通知
                    if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                        publish_notification(new_notification)
                    else:
                        publish_notification(new_notification.id)
                    # 成功新建组织申请
                    html_display['warn_code'] = 2
                    html_display['warn_message'] = "已成功取消申请！"
                    return render(request, "applyOrganization.html", locals())
            # 参数合法性检查 TODO 修改为pos的合法性
            
            if edit:
                context = utils.check_newpos_request(request,prepos)  # check
            else:
                context = utils.check_newpos_request(request)  # check
            if context['warn_code'] != 0:
                html_display['warn_code'] = context['warn_code']
                html_display['warn_message'] = "新建人事申请失败。" + \
                    context['warn_msg']
                return render(request, "applyOrganization.html", locals())
            
            # 新建人事申请
            if edit == 0:
                org = Organization.objects.get(oname=context['oname'])
                apply_pos = context['apply_pos']
                apply_type = context['apply_type']
                try:
                    _, pos = Position.objects.create_application(me, org, apply_type=apply_type, apply_pos=apply_pos)
                except:
                    html_display['warn_code'] = 1
                    if apply_type == 'JOIN':
                        html_display['warn_message'] = "您已加入该组织，不能重复加入！"
                    elif apply_type == 'TRANSFER':
                        html_display['warn_message'] = "您未加入该组织，不能修改职位！"
                    elif apply_type == 'WITHDRAW':
                        html_display['warn_message'] = "您未加入该组织，不能退出该组织！"
                    return render(request, "applyOrganization.html", locals())
                try:
                    new_pos = NewPosition.objects.create(position=pos, application=context['application'],status=NewPosition.NewPosStatus.PENDING,apply_pos=apply_pos,apply_type=apply_type)
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建人事申请信息失败。请检查输入or联系管理员"
                    return render(request, "applyOrganization.html", locals())
                
                with transaction.atomic():
                    content = "新建人事申请：“{name}申请{oname}".format(
                        name=new_pos.position.org.oname, oname=new_pos.position.person.name)
                    # 审核人员信息,暂定为各个otype的incharge
                    Auditor = new_pos.position.org.organization_id  #审核老师
                    URL = ""
                    new_notification = notification_create(Auditor, request.user,
                                                            Notification.Type.NEEDDO,
                                                            Notification.Title.VERIFY_INFORM, content,
                                                            URL)
                    en_pw = hash_coder.encode(str(new_pos.id) + '人事申请' +
                                                str(new_notification.id))
                    URL = "/auditPosition?newpos_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                        id=new_pos.id, nid=new_notification.id, en_pw=en_pw)
                    # URL = request.build_absolute_uri(URL)
                    new_notification.URL = URL
                    new_notification.save()
                try:
                    pass
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "applyOrganization.html", locals())

                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                
                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功发送，请耐心等待组织审批！"
                return render(request, "applyOrganization.html", locals())
            # 修改组织申请
            else:
                # 修改信息
                try:
                    with transaction.atomic():
                        prepos.oname = context['oname']
                        prepos.application = context['application']
                        prepos.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "修改申请失败。请检查输入or联系管理员"
                    return render(request, "applyOrganization.html", locals())

                # 发送通知
                try:
                    with transaction.atomic():
                        content = "“{name}”修改了申请信息，请您继续审核！".format(
                            name=prepos.position.person.name)
                        # 审核人员信息,暂定为各个otype的incharge
                        Auditor = prepos.position.org.organization_id  # 审核老师
                        URL = ""
                        new_notification = notification_create(Auditor, request.user,
                                                               Notification.Type.NEEDDO,
                                                               Notification.Title.VERIFY_INFORM, content,
                                                               URL)
                        en_pw = hash_coder.encode(str(prepos.id) + '人事申请' +
                                                  str(new_notification.id))
                        URL = "/auditPosition?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=prepos.id, nid=new_notification.id, en_pw=en_pw)
                        # URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                    return render(request, "applyOrganization.html", locals())
                # 成功新建组织申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "申请已成功发送，请耐心等待组织审批！"
                if notification_id!=-1:
                    context = notification_status_change(notification_id)
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
                    

    if request.GET.get("org") is not None:
        exist_org = True
        html_display['default_oname'] = Organization.objects.get(organization_id__id=request.GET.get("org")).oname
    else:
        exist_org = False
        
            
    return render(request, "applyOrganization.html", locals())


# 修改和审批申请新建组织的信息，只用该函数即可
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def auditPosition(request):
    valid, user_type, html_display = utils.check_user_type(request.user)

    me = utils.get_person_or_org(request.user, user_type)
    html_display['is_myself'] = True
    html_display['warn_code'] = 0
    commentable=0
    notification_id=-1

    try:  # 获取申请信息
        id = int(request.GET.get('newpos_id', -1))  # 新建组织ID
        notification_id = int(request.GET.get('notifi_id', -1))  # 通知ID
        if id == -1 or notification_id == -1:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
        en_pw = str(request.GET.get('enpw'))
        if hash_coder.verify(str(id) + '人事申请' + str(notification_id),
                             en_pw) == False:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
            return redirect('/notifications/' +
                            '?warn_code={}&warn_message={}'.format(
                                html_display['warn_code'], html_display['warn_message']))
        prepos = NewPosition.objects.get(id=id)
        notification = Notification.objects.get(id=notification_id)
    except:
        html_display['warn_code'] = 1
        html_display['warn_message'] = "获取申请信息失败，请联系管理员。"
        return redirect('/notifications/' +
                        '?warn_code={}&warn_message={}'.format(
                            html_display['warn_code'], html_display['warn_message']))
        # 是否为组织
    if request.user != prepos.position.org.organization_id:
        return redirect('/notifications/')
    if prepos.status == NewPosition.NewPosStatus.PENDING:  # 正在申请中，可以评论。
        commentable = 1  # 可以评论
    if prepos.status==NewPosition.NewPosStatus.CANCELED and notification.status==Notification.Status.UNDONE:
        #未读变已读
        notification_status_change(notification_id)
    if prepos.status==NewPosition.NewPosStatus.CONFIRMED and notification.status==Notification.Status.UNDONE:
        #未读变已读
        notification_status_change(notification_id)
    
    # 以下需要在前端呈现
    comments = prepos.comments.order_by('time')  # 加载评论
    html_display['oname'] = prepos.position.org.oname
    html_display['apply_pos'] = prepos.apply_pos
    html_display['apply_type'] = prepos.apply_type
    html_display['applicant'] = utils.get_person_or_org(prepos.position.person.person_id)
    html_display["app_avatar_path"] = utils.get_user_ava(html_display['applicant'],"Person")
    html_display['application'] = prepos.application

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建人事审核"
    bar_display["navbar_name"] = "新建人事审核"


    if request.method == "POST" and request.POST:
        if int(request.POST.get('comment_submit',-1))==1:  # 新建评论信息，并保存
            context = addComment(request, prepos)
            if context['warn_code'] == 1:
                html_display['warn_code'] = 1
                html_display['warn_message'] = context['warn_code']
        # 对于审核老师来说，有三种操作，通过，申请需要修改和拒绝
        else:
            submit = int(request.POST.get('submit', -1))
            if submit == 2:  # 通过 # TODO 怎么是写死的？？？？？
                try:
                    with transaction.atomic():  # 新建组织
                        application = prepos.position
                        if application.apply_type == Position.ApplyType.JOIN:
                            application.status = Position.Status.INSERVICE
                            application.pos = application.apply_pos
                        elif application.apply_type == Position.ApplyType.WITHDRAW:
                            application.status = Position.Status.DEPART
                        elif application.apply_type == Position.ApplyType.TRANSFER:
                            application.pos = application.apply_pos
                        application.apply_status = Position.ApplyStatus.PASS
                        application.save()

                        prepos.status = NewPosition.NewPosStatus.CONFIRMED
                        prepos.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "职位创建失败。请联系管理员！"
                    return render(request, "position_audit.html", locals())
                
                try:  # 发送给申请者的通过通知
                    with transaction.atomic():
                        content = "新建人事申请已通过，组织名为 “{oname}” ，您的职务为 “{position}”。恭喜！"\
                            .format(oname=application.org.oname, position=application.pos)
                        receiver = application.person.person_id  # 通知接收者
                        URL = ""
                        new_notification = notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                                               Notification.Title.VERIFY_INFORM, content, URL)
                        URL = "/applyOrganization/?neworg_id={id}".format(id=prepos.id)
                        new_notification.URL=URL
                        new_notification.save()

                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())
                 # 成功新建组织
                html_display['warn_code'] = 2
                html_display['warn_message'] = "已通过新建人事申请，组织已创建！"
                if notification_id!=-1:
                    context = notification_status_change(notification_id)
                if context['warn_code'] != 0:
                    html_display['warn_message'] = context['warn_message']
                # 微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                return render(request, "organization_audit.html", locals())
            elif submit == 3:  # 拒绝
                try:  # 发送给申请者的拒绝通知
                    with transaction.atomic():
                        prepos.position.apply_status = Position.ApplyStatus.REJECT
                        prepos.status = NewPosition.NewPosStatus.REFUSED
                        prepos.save()
                        content = "很遗憾，新建人事申请未通过！"
                        receiver = prepos.position.person.person_id  # 通知接收者
                        URL = ""

                        new_notification = notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                                               Notification.Title.VERIFY_INFORM, content, URL)
                        URL = "/applyOrganization/?neworg_id={id}".format(id=prepos.id)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "position_audit.html", locals())

                # 拒绝成功
                html_display['warn_code'] = 2
                html_display['warn_message'] = "已拒绝人事申请！"
                if notification_id != -1:
                    context = notification_status_change(notification_id)
                
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
                return render(request, "position_audit.html", locals())
    
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建人事审核"
    bar_display["navbar_name"] = "新建人事审核"
    print(html_display)

    return render(request, "position_audit.html", locals())        
                

# YWolfeee: 重构人事申请页面 Aug 24 12:30 UTC-8
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def modifyPosition(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身

    # 前端使用量user_type，表示观察者是组织还是个人

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None

    # 根据是否有newid来判断是否是第一次
    position_id = request.GET.get("pos_id", None)

    if position_id is not None: # 如果存在对应组织
        try:    # 尝试获取已经新建的Position
            application = ModifyPosition.objects.get(id = position_id)
            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者被申请组织之一
            assert (application.org == me) or (application.person == me) 
        except: #恶意跳转
            return redirect("/welcome/")
        is_new_application = False # 前端使用量, 表示是老申请还是新的
        applied_org = application.org

    else:   # 如果不存在id, 默认应该传入org_name参数
        org_name = request.GET.get("org_name", None)
        try:
            applied_org = Organization.objects.activated().get(oname=org_name)
            assert user_type == "Person" # 只有个人能看到这个新建申请的界面

        except:
            # 非法的名字, 出现恶意修改参数的情况
            return redirect("/welcome/")
        
        # 查找已经存在的处理中的申请
        try:
            application = ModifyPosition.objects.get(
                org = applied_org, person = me, status = ModifyPosition.Status.PENDING)
            is_new_application = False # 如果找到, 直接跳转老申请
        except:
            is_new_application = True
        
    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在个人新建申请的时候才可能出现，对应位is_new_application
        applied_org为对应的组织
        接下来POST
    '''

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST":
        # 如果是状态变更
        if request.POST.get("post_type", None) is not None:            

            # 主要操作函数，更新申请状态
            context = update_pos_application(application, me, user_type, 
                    applied_org, request.POST)

            if context["warn_code"] == 2:   # 成功修改申请
                # 回传id 防止意外的锁操作
                application = ModifyPosition.objects.get(id = context["application_id"])
                is_new_application = False  #状态变更

                # 处理通知相关的操作，并根据情况发送微信
                # 默认需要成功,失败也不是用户的问题，直接给管理员报错
                make_relevant_notification(application, request.POST)    

            elif context["warn_code"] != 1: # 没有返回操作提示
                raise NotImplementedError("处理人事申请中出现未预见状态，请联系管理员处理！")   
            

        else:   # 如果是新增评论
            # 权限检查
            allow_comment = True if (not is_new_application) and (
                application.is_pending()) else False
            if not allow_comment:   # 存在不合法的操作
                return redirect(
                    "/welcome/?warn_code=1&warn_message=存在不合法操作,请与管理员联系!")
            context = addComment(request, application, application.org.organization_id if user_type == 'Person' else application.person.person_id)

        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    # 申请的职务类型, 对应ModifyPosition.ApplyType
    apply_type_list = {
        w:{
                    # 对应的status设置, 属于ApplyType
            'display' : str(w),  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for w in ModifyPosition.ApplyType
    }
    # 申请的职务等级
    position_name_list = [
        {
            'display' : applied_org.otype.get_name(i),  #名称
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False,   # 是否默认选中这个量
        }
        for i in range(applied_org.otype.get_length())
    ]

    '''
        个人：可能是初次申请或者是修改申请
        组织：可能是审核申请
        # TODO 也可能是两边都想自由的查看这个申请

        区别：
            (1) 整个表单允不允许修改和评论
            (2) 变量的默认值[可以全部统一做]
    '''
    
    # (1) 是否允许修改&允许评论
    # 用户写表格?
    allow_form_edit = True if (user_type == "Person") and (
                is_new_application or application.is_pending()) else False
    # 组织审核?
    allow_audit_submit = True if (not user_type == "Person") and (not is_new_application) and (
                application.is_pending()) else False
    # 评论区?
    allow_comment = True if (not is_new_application) and (application.is_pending()) \
                    else False

    # (2) 表单变量的默认值

        # 首先禁用一些选项
    
    # 评论区
    commentable = allow_comment
    comments = showComment(application) if application is not None else None
    # 用于前端展示：如果是新申请，申请人即“me”，否则从application获取。
    apply_person = me if is_new_application else application.person
    app_avatar_path = utils.get_user_ava(apply_person,"Person")
    # 获取个人与组织[在当前学年]的关系
    current_pos_list = Position.objects.current().filter(person=apply_person,org=applied_org)
    # 应当假设只有至多一个类型

    # 检查该同学是否已经属于这个组织
    whether_belong = True if len(current_pos_list) and \
        current_pos_list[0].status == Position.Status.INSERVICE else False
    if whether_belong:
        # 禁用掉加入组织
        apply_type_list[ModifyPosition.ApplyType.JOIN]['disabled'] = True
        # 禁用掉修改职位中的自己的那个等级
        position_name_list[current_pos_list[0].get_pos_number()]["disabled"] = True
        #current_pos_name = applied_org.otype.get_name(current_pos_list[0].pos)
    else:   #不属于组织, 只能选择加入组织
        apply_type_list[ModifyPosition.ApplyType.WITHDRAW]['disabled'] = True
        apply_type_list[ModifyPosition.ApplyType.TRANSFER]['disabled'] = True

        # TODO: 设置默认值

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="人事申请详情")
    return render(request, "modify_position.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def showPosition(request):
    '''
    人事的聚合界面
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)

    # 查看人事聚合页面：拉取个人或组织相关的申请
    if user_type == "Person":
        shown_instances = ModifyPosition.objects.filter(person=me)
    else:
        shown_instances = ModifyPosition.objects.filter(org=me)

    shown_instances = shown_instances.order_by('-modify_time', '-time')

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name = "人事申请")
    return render(request, 'showPosition.html', locals())

# 修改和审批申请新建组织的信息，只用该函数即可
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def auditOrganization(request):
    """
    对于审核老师老师：第一次进入的审核，如果申请需要修改，则有之后的下一次审核等
    """
    TERMINATE_STATUSES = [
        NewOrganization.NewOrgStatus.CONFIRMED,
        NewOrganization.NewOrgStatus.CANCELED,
        NewOrganization.NewOrgStatus.REFUSED,
    ]
    valid, user_type, html_display = utils.check_user_type(request.user)

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    html_display["warn_code"] = 0
    commentable = 0
    notification_id = -1
    try:  # 获取申请信息
        id = int(request.GET.get("neworg_id", -1))  # 新建组织ID
        notification_id = int(request.GET.get("notifi_id", -1))  # 通知ID
        if id == -1 or notification_id == -1:
            raise Exception("URL参数不足")
        en_pw = str(request.GET.get("enpw"))
        if hash_coder.verify(str(id) + "新建组织" + str(notification_id), en_pw) == False:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "该URL被篡改，请输入正确的URL地址"
            return redirect(
                "/notifications/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        preorg = NewOrganization.objects.get(id=id)
        notification = Notification.objects.get(id=notification_id)
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "获取申请信息失败，请联系管理员。"
        return redirect(
            "/notifications/"
            + "?warn_code={}&warn_message={}".format(
                html_display["warn_code"], html_display["warn_message"]
            )
        )
        # 是否为审核老师
    if request.user != preorg.otype.incharge.person_id:
        return redirect('/notifications/')
    # 以下需要在前端呈现
    html_display['oname'] = preorg.oname
    html_display['otype_name'] = preorg.otype.otype_name
    html_display['applicant'] = utils.get_person_or_org(preorg.pos)
    html_display["app_avatar_path"] = utils.get_user_ava(html_display['applicant'], "Person")
    html_display['introduction'] = preorg.introduction
    html_display['application'] = preorg.application

    org_avatar_path = utils.get_user_ava(preorg, "Organization")

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织审核"
    bar_display["navbar_name"] = "新建组织审核"

    if request.method == "POST" and request.POST:
        if int(request.POST.get("comment_submit", -1)) == 1:  # 新建评论信息，并保存
            context = addComment(request, preorg)
            if context['warn_code'] == 1:
                html_display['warn_code'] = 1
                html_display['warn_message'] = context['warn_message']
            else:
                try:  # 发送给评论通知
                    with transaction.atomic():
                        text = str(context['new_comment'].text)
                        if len(text) >= 32:
                            text = text[:31] + "……"
                        content = "{teacher_name}老师给您的组织申请留有新的评论".format(
                            teacher_name=me.name)
                        if text != "":
                            content += ":“{text}”".format(text=text)
                        receiver = preorg.pos  # 通知接收者
                        URL = ""
                        new_notification = notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                                               Notification.Title.VERIFY_INFORM, content, URL)
                        en_pw = hash_coder.encode(str(preorg.id) + '新建组织' + str(new_notification.id))
                        URL = "/addOrganization?neworg_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=preorg.id, nid=new_notification.id, en_pw=en_pw)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的评论通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())
                # 微信通知
                publish_notification(new_notification)
                html_display['warn_code'] = 2
                html_display['warn_message'] = "评论成功！"

        # 对于审核老师来说，有三种操作，通过，申请需要修改和拒绝
        else:
            submit = int(request.POST.get("submit", -1))
            if submit == 2:  # 通过
                try:
                    with transaction.atomic():  # 新建组织

                        username = utils.find_max_oname()  # 组织的代号最大值

                        user = User.objects.create(username=username)
                        password = utils.random_code_init()
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
                        pos = Position.objects.create(
                            person=charger,
                            org=org,
                            pos=0,
                            status=Position.Status.INSERVICE,
                        )
                        pos.save()

                        preorg.status = preorg.NewOrgStatus.CONFIRMED
                        preorg.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建组织失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())

                try:  # 发送给申请者的通过通知
                    with transaction.atomic():
                        content = (
                            "新建组织申请已通过，组织编号为 “{username}” ，初始密码为 “{password}” ，请尽快登录修改密码。"
                            "登录方式：(1)在负责人账户点击左侧“切换账号”；(2)从登录页面用组织编号或组织名称以及密码登录。".format(
                                username=username, password=password
                            )
                        )
                        receiver = preorg.pos  # 通知接收者
                        URL = ""
                        # URL = request.build_absolute_uri(URL)
                        new_notification = notification_create(
                            receiver,
                            request.user,
                            Notification.Type.NEEDREAD,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )
                        URL = "/addOrganization/?neworg_id={id}".format(id=preorg.id)
                        new_notification.URL = URL
                        new_notification.save()

                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())
                # 成功新建组织
                html_display["warn_code"] = 2
                html_display[
                    "warn_message"
                ] = "已通过新建“{oname}”{otype_name}的申请，该组织已创建！".format(
                    oname=preorg.oname, otype_name=preorg.otype.otype_name
                )
                if notification_id != -1:
                    context = notification_status_change(notification_id)
                if context["warn_code"] != 2:
                    html_display["warn_message"] = context["warn_message"]
                # 微信通知
                publish_notification(new_notification)
            elif submit == 3:  # 拒绝
                try:  # 发送给申请者的拒绝通知
                    with transaction.atomic():
                        preorg.status = NewOrganization.NewOrgStatus.REFUSED
                        preorg.save()
                        content = "很遗憾，“{oname}”{otype_name}的新建组织申请未通过！".format(
                            oname=preorg.oname, otype_name=preorg.otype.otype_name
                        )
                        receiver = preorg.pos  # 通知接收者
                        URL = ""
                        # URL = request.build_absolute_uri(URL)
                        new_notification = notification_create(
                            receiver,
                            request.user,
                            Notification.Type.NEEDREAD,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )
                        URL = "/addOrganization/?neworg_id={id}".format(id=preorg.id)
                        new_notification.URL = URL
                        new_notification.save()

                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "organization_audit.html", locals())

                # 拒绝成功
                html_display["warn_code"] = 2
                html_display[
                    "warn_message"
                ] = "已拒绝“{oname}”{otype_name}的新建组织申请！".format(
                    oname=preorg.oname, otype_name=preorg.otype.otype_name
                )
                if notification_id != -1:
                    context = notification_status_change(
                        notification_id, Notification.Status.DONE
                    )
                # 微信通知
                publish_notification(new_notification)
            else:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "提交出现无法处理的未知参数，请联系管理员。"

    if preorg.status == NewOrganization.NewOrgStatus.PENDING:  # 正在申请中，可以评论。
        commentable = 1  # 可以评论
    if preorg.status in TERMINATE_STATUSES and notification.status == Notification.Status.UNDONE:
        # 未读变已读
        notification_status_change(notification_id, Notification.Status.DONE)

    if preorg.status not in TERMINATE_STATUSES:  # 正在申请中，可以评论。
        commentable = 1  # 可以评论
    if (
            preorg.status in TERMINATE_STATUSES
            and notification.status == Notification.Status.UNDONE
    ):
        # 未读变已读
        notification_status_change(notification_id, Notification.Status.DONE)
    comments = showComment(preorg)  # 加载评论
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建组织审核"
    bar_display["navbar_name"] = "新建组织审核"

    return render(request, "organization_audit.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def showReimbursement(request):
    """
    报销信息的聚合界面
    对审核老师进行了特判
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_auditor = False
    if user_type == "Person":
        try:
            person = utils.get_person_or_org(request.user, user_type)
            if person.name == local_dict["audit_teacher"]["Funds"]:
                is_auditor = True
        except:
            pass
        if not is_auditor:
            html_display["warn_code"] = 1
            html_display["warn_code"] = "请不要使用个人账号申请报销！"
            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )

    if is_auditor:
        shown_instances = Reimbursement.objects
    else:
        shown_instances = Reimbursement.objects.filter(pos=request.user)
    shown_instances = shown_instances.order_by("-modify_time", "-time")
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "报销信息"
    bar_display["navbar_name"] = "报销信息"
    return render(request, "reimbursement_show.html", locals())


# 新建或修改报销信息
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def addReimbursement(request):
    """
    新建报销信息
    """
    TERMINATE_STATUSES = [
        Reimbursement.ReimburseStatus.CONFIRMED,
        Reimbursement.ReimburseStatus.CANCELED,
        Reimbursement.ReimburseStatus.REFUSED,
    ]
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Person":
        return redirect("/welcome/")  # test

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    html_display["warn_code"] = 0

    reimbursed_act_ids = (
        Reimbursement.objects.all()
            .exclude(
            status=Reimbursement.ReimburseStatus.CANCELED  # 未取消报销的
            # 未被拒绝的
        )
            .exclude(status=Reimbursement.ReimburseStatus.REFUSED)
            .values_list("activity_id", flat=True)
    )
    activities = (
        Activity.objects.activated()  # 本学期的
            .filter(organization_id=me)  # 本部门组织的
            .filter(status=Activity.Status.END)  # 已结束的
            .exclude(id__in=reimbursed_act_ids)  # 还没有报销的
    )  # 这种写法是为了方便随时取消某个条件
    # 新版侧边栏, 顶栏等的呈现，采用
    # bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建报销申请"
    bar_display["navbar_name"] = "新建报销申请"

    YQP = float(me.YQPoint)  # 组织剩余的元气值
    present = 0  # 前端需要，1代表能展示，0代表初始申请
    commentable = 0  # 前端需要，表示能否评论。
    edit = 0  # 前端需要，表示第一次申请后修改
    notification_id = -1

    if request.GET.get("reimb_id") is not None:
        # 不是初次申请，而是修改或访问记录
        # 只要id正确就能显示
        # 是否能够取消,
        # 检查是否为本人，
        notification_id = request.GET.get("notifi_id", -1)
        try:
            id = int(request.GET.get("reimb_id"))  # 报销信息的ID
            pre_reimb = Reimbursement.objects.get(id=id)
            if notification_id != -1:
                # 说明是通过信箱进入的，检查加密
                notification_id = int(request.GET.get("notifi_id"))  # 通知ID
                en_pw = str(request.GET.get("enpw"))
                if (
                        hash_coder.verify(str(id) + "新建报销" + str(notification_id), en_pw)
                        == False
                ):
                    raise Exception("报销加密验证未通过")
                notification = Notification.objects.get(id=notification_id)
                if notification.status == Notification.Status.DELETE:
                    raise Exception("不能通过已删除的通知查看报销信息！")
        except:
            html_display['warn_code'] = 1
            html_display['warn_message'] = "该URL被篡改，请输入正确的URL地址"
            return redirect("/welcome/")
            return redirect('/notifications/' + '?warn_code={}&warn_message={}'.format(
                html_display['warn_code'], html_display['warn_message']))
        if pre_reimb.pos != request.user:  # 判断是否为本人
            html_display['warn_code'] = 1
            html_display['warn_message'] = "您没有权力查看此通知"
            return redirect('/notifications/' + '?warn_code={}&warn_message={}'.format(
                html_display['warn_code'], html_display['warn_message']))
        if pre_reimb.status not in TERMINATE_STATUSES:  # 正在申请中，可以评论。
            commentable = 1  # 可以评论
            edit = 1  # 能展示也能修改
        present = 1  # 只要id正确就能显示
    if present:  # 第一次打开页面信息的准备工作,以下均为前端展示需要
        comments = showComment(pre_reimb)
        html_display['audit_activity'] = pre_reimb.activity  # 正在报销的活动，避免被过滤掉
        html_display['amount'] = pre_reimb.amount  # 报销金额
        html_display['message'] = pre_reimb.message  # 备注信息

    username = local_dict["audit_teacher"]["Funds"]
    Auditor = User.objects.get(username=username)
    auditor_name = utils.get_person_or_org(Auditor).name
    if request.method == "POST" and request.POST:

        if request.POST.get("comment_submit") is not None:  # 新建评论信息，并保存
            context = addComment(request, pre_reimb)
            if context['warn_code'] == 1:
                html_display['warn_code'] = 1
                html_display['warn_message'] = context['warn_message']
            else:
                try:  # 发送给评论通知
                    with transaction.atomic():
                        text = str(context["new_comment"].text)
                        if len(text) >= 32:
                            text = text[:31] + "……"
                        content = "“{act_name}”的经费申请有了新的评论：“{text}” ".format(
                            act_name=pre_reimb.activity.title, text=text
                        )
                        URL = ""
                        new_notification = notification_create(
                            Auditor,
                            request.user,
                            Notification.Type.NEEDREAD,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )
                        en_pw = hash_coder.encode(
                            str(pre_reimb.id) + "新建报销" + str(new_notification.id)
                        )
                        URL = "/auditReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=pre_reimb.id, nid=new_notification.id, en_pw=en_pw
                        )
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建发送给审核老师的评论通知失败。请联系管理员！"
                    return render(request, "reimbursement_add.html", locals())
                # 微信通知
                publish_notification(new_notification)
                html_display['warn_code'] = 2
                html_display['warn_message'] = "评论成功！"
        else:  # 取消+新建+修改
            # 取消
            need_cancel = int(request.POST.get("cancel_submit", -1))
            if need_cancel == 1:  # 1代表取消
                if edit:
                    with transaction.atomic():  # 修改状态为取消
                        pre_reimb.status = Reimbursement.ReimburseStatus.CANCELED
                        pre_reimb.save()
                    try:
                        with transaction.atomic():
                            content = "“{act_name}”的经费申请已取消".format(
                                act_name=pre_reimb.activity.title
                            )
                            URL = ""
                            new_notification = notification_create(
                                Auditor,
                                request.user,
                                Notification.Type.NEEDREAD,
                                Notification.Title.VERIFY_INFORM,
                                content,
                                URL,
                            )
                            en_pw = hash_coder.encode(
                                str(pre_reimb.id) + "新建报销" + str(new_notification.id)
                            )
                            URL = "/auditReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                                id=pre_reimb.id, nid=new_notification.id, en_pw=en_pw
                            )
                            # URL = request.build_absolute_uri(URL)
                            new_notification.URL = URL
                            new_notification.save()
                    except:
                        html_display["warn_code"] = 1
                        html_display["warn_message"] = "创建给审核老师的取消通知失败。请联系管理员。"
                        return render(request, "reimbursement_add.html", locals())
                # 微信通知
                publish_notification(new_notification)
                # 成功取消经费申请
                html_display['warn_code'] = 2
                html_display['warn_message'] = "已成功取消“{act_name}”的经费申请！".format(act_name=pre_reimb.activity.title)
                edit = 0
                commentable = 0
            else:
                if edit == 0:
                    # 活动实例
                    try:
                        reimb_act_id = int(request.POST.get('activity_id'))
                        reimb_act = Activity.objects.get(id=reimb_act_id)
                        if reimb_act not in activities:  # 防止篡改POST导致伪造别人的报销活动
                            html_display['warn_code'] = 1
                            html_display['warn_message'] = "找不到该活动，请检查报销的活动的合法性！"
                            return render(request, "reimbursement_add.html", locals())
                    except:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "找不到该活动，请检查报销的活动的合法性！"
                        return render(request, "reimbursement_add.html", locals())
                # YQP合法性的检查

                try:
                    reimb_YQP = float(request.POST.get('YQP'))
                    if reimb_YQP < 0:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "申请失败，报销的元气值不能为负值！"
                        return render(request, "reimbursement_add.html", locals())
                    if reimb_YQP > YQP:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "申请失败，报销的元气值不能超过组织当前元气值！"
                        return render(request, "reimbursement_add.html", locals())
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "元气值不能为空，请完整填写。"
                    return render(request, "reimbursement_add.html", locals())

                message = str(request.POST.get('message'))  # 报销说明
                if message == "":
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "报销说明不能为空，请完整填写。"
                    return render(request, "reimbursement_add.html", locals())

                if edit == 0:
                    try:  # 创建报销信息
                        images = request.FILES.getlist('images')
                        for image in images:
                            if utils.if_image(image) == False:
                                html_display['warn_code'] = 1
                                html_display['warn_message'] = "上传的附件只支持图片格式。"
                                return render(request, "reimbursement_add.html", locals())
                        with transaction.atomic():
                            new_reimb = Reimbursement.objects.create(
                                activity=reimb_act, amount=reimb_YQP, pos=request.user)
                            new_reimb.message = message
                            new_reimb.save()
                            # 创建评论保存图片
                            if images != []:
                                text = "以下默认为初始的报销材料"
                                reim_comment = Comment.objects.create(
                                    commentbase=new_reimb, commentator=request.user)
                                reim_comment.text = text
                                reim_comment.save()
                                for payload in images:
                                    CommentPhoto.objects.create(
                                        image=payload, comment=reim_comment)
                    except:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "新建经费申请失败，请联系管理员！"
                        return render(request, "reimbursement_add.html", locals())

                    try:  # 创建对应通知
                        with transaction.atomic():
                            content = "新的经费申请：{org_name}“{act_name}”！".format(
                                org_name=me.oname, act_name=new_reimb.activity.title)
                            URL = ""
                            new_notification = notification_create(Auditor, request.user,
                                                                   Notification.Type.NEEDDO,
                                                                   Notification.Title.VERIFY_INFORM, content,
                                                                   URL)
                            en_pw = hash_coder.encode(str(new_reimb.id) + '新建报销' +
                                                      str(new_notification.id))
                            URL = "/auditReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                                id=new_reimb.id, nid=new_notification.id, en_pw=en_pw)
                            # URL = request.build_absolute_uri(URL)
                            new_notification.URL = URL
                            new_notification.save()
                    except:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                        return render(request, "reimbursement_add.html", locals())

                    # 微信通知
                    publish_notification(new_notification)
                    # 成功发送报销申请
                    html_display['warn_code'] = 2
                    html_display['warn_message'] = "经费申请已成功发送，请耐心等待{auditor_name}老师审批！" \
                        .format(auditor_name=auditor_name)
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
                            content = "{org_name}“{act_name}”的经费申请已修改！".format(
                                org_name=me.oname, act_name=pre_reimb.activity.title)
                            # 在local_json.json新增审批人员信息,暂定为YPadmin
                            URL = ""
                            new_notification = notification_create(Auditor, request.user,
                                                                   Notification.Type.NEEDDO,
                                                                   Notification.Title.VERIFY_INFORM, content,
                                                                   URL)

                            en_pw = hash_coder.encode(str(pre_reimb.id) + '新建报销' +
                                                      str(new_notification.id))
                            URL = "/auditReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                                id=pre_reimb.id, nid=new_notification.id, en_pw=en_pw)
                            # URL = request.build_absolute_uri(URL)
                            new_notification.URL = URL
                            new_notification.save()
                    except:
                        html_display['warn_code'] = 1
                        html_display['warn_message'] = "创建通知失败。请检查输入or联系管理员"
                        return render(request, "reimbursement_add.html", locals())
                    # 成功报销申请
                    html_display['warn_code'] = 2
                    html_display['warn_message'] = "经费申请已成功修改，请耐心等待{auditor_name}老师审批！" \
                        .format(auditor_name=auditor_name)
                    if notification_id != -1:
                        context = notification_status_change(notification_id, Notification.Status.DONE)
                        if context['warn_code'] == 1:
                            html_display['warn_message'] = context['warn_message']
                    # 发送微信消息
                    publish_notification(new_notification)
    if present:  # 第一次打开页面信息的准备工作,以下均为前端展示需要
        comments = showComment(pre_reimb)
        html_display['audit_activity'] = pre_reimb.activity  # 正在报销的活动，避免被过滤掉
        html_display['amount'] = pre_reimb.amount  # 报销金额
        html_display['message'] = pre_reimb.message  # 备注信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "新建报销"
    bar_display["navbar_name"] = "新建报销"
    return render(request, "reimbursement_add.html", locals())


# 审核报销信息
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def auditReimbursement(request):
    """
    审核报销信息
    """
    TERMINATE_STATUSES = [
        Reimbursement.ReimburseStatus.CONFIRMED,
        Reimbursement.ReimburseStatus.CANCELED,
        Reimbursement.ReimburseStatus.REFUSED,
    ]
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type == "Organization":
        return redirect("/welcome/")  # test
    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    html_display["warn_code"] = 0
    html_display["warn_message"] = ""

    commentable = 0
    notification_id = -1
    # 检查是否为正确的审核老师
    if request.user.username != local_dict["audit_teacher"]["Funds"]:
        return redirect("/notifications/")
    try:  # 获取申请信息
        id = int(request.GET.get("reimb_id", -1))  # 报销信息的ID
        notification_id = int(request.GET.get("notifi_id", -1))  # 通知ID

        if id == -1 or notification_id == -1:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "获取申请信息失败，请联系管理员。"
            return redirect(
                "/notifications/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        en_pw = str(request.GET.get("enpw"))
        if hash_coder.verify(str(id) + "新建报销" + str(notification_id), en_pw) == False:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "该URL被篡改，请输入正确的URL地址"
            return redirect(
                "/notifications/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        new_reimb = Reimbursement.objects.get(id=id)
        notification = Notification.objects.get(id=notification_id)
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "获取申请信息失败，请联系管理员。"
        return redirect(
            "/notifications/"
            + "?warn_code={}&warn_message={}".format(
                html_display["warn_code"], html_display["warn_message"]
            )
        )

    # 新版侧边栏, 顶栏等的呈现，采用
    # bar_display, 必须放在render前最后一步
    # TODO: 整理页面返回逻辑，统一返回render的地方
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "报销审核"
    bar_display["navbar_name"] = "报销审核"

    # 以下前端展示
    comments = showComment(new_reimb)  # 加载评论
    html_display['activity'] = new_reimb.activity  # 报销活动
    html_display['amount'] = new_reimb.amount  # 报销金额
    html_display['message'] = new_reimb.message  # 报销说明
    html_display['apply_time'] = new_reimb.time  # 申请时间
    html_display['applicant'] = utils.get_person_or_org(new_reimb.pos)  # 申请组织
    html_display['app_avatar_path'] = utils.get_user_ava(html_display['applicant'], "Organization")  # 申请组织的头像
    html_display['our_college'] = Organization.objects.get(oname="元培学院")  # 获取元培学院的元气值

    if request.method == "POST" and request.POST:

        if request.POST.get("comment_submit") is not None:  # 新建评论信息，并保存
            context = addComment(request, new_reimb)
            if context['warn_code'] == 1:
                html_display['warn_code'] = 1
                html_display['warn_message'] = context['warn_message']
            else:
                try:  # 发送给评论通知
                    with transaction.atomic():
                        text = str(context['new_comment'].text)
                        if len(text) >= 32:
                            text = text[:31] + "……"
                        content = "{teacher_name}老师给您的经费申请留有新的评论".format(
                            teacher_name=me.name)
                        if text != "":
                            content += ":”{text}“".format(text=text)
                        receiver = new_reimb.pos  # 通知接收者
                        URL = ""
                        new_notification = notification_create(receiver, request.user, Notification.Type.NEEDREAD,
                                                               Notification.Title.VERIFY_INFORM, content, URL)
                        en_pw = hash_coder.encode(str(new_reimb.id) + '新建报销' + str(new_notification.id))
                        URL = "/addReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=new_reimb.id, nid=new_notification.id, en_pw=en_pw)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display['warn_code'] = 1
                    html_display['warn_message'] = "创建发送给申请者的评论通知失败。请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())
                # 微信通知
                if getattr(publish_notification, 'ENABLE_INSTANCE', False):
                    publish_notification(new_notification)
                else:
                    publish_notification(new_notification.id)
                html_display['warn_code'] = 2
                html_display['warn_message'] = "评论成功！"


        # 审核老师的两种操作：通过，和拒绝
        else:
            submit = int(request.POST.get("submit", -1))
            if submit == 2:  # 通过
                org = new_reimb.pos.organization

                try:
                    with transaction.atomic():
                        if org.YQPoint < new_reimb.amount:
                            html_display["warn_code"] = 1
                            html_display["warn_message"] = "当前组织没有足够的元气值。报销申请无法通过。"
                        else:  # 修改对应组织的元气值
                            org.YQPoint -= new_reimb.amount
                            org.save()
                            new_reimb.status = Reimbursement.ReimburseStatus.CONFIRMED
                            new_reimb.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "修改元气值失败。报销申请无法通过，请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())

                try:  # 发送给申请者的通过通知或者是没有足够元气值的通知
                    with transaction.atomic():
                        if html_display["warn_code"] == 1:
                            content = "{act_name}的报销申请由于组织元气值不足无法通过，请补充元气值至{amount}以上再点击通知继续申请！".format(
                                act_name=new_reimb.activity.title,
                                amount=new_reimb.amount,
                            )
                            typename = Notification.Type.NEEDDO
                            URL = ""
                        else:
                            content = "{act_name}的报销申请已通过，扣除元气值{amount}".format(
                                act_name=new_reimb.activity.title,
                                amount=new_reimb.amount,
                            )
                            typename = Notification.Type.NEEDREAD
                            URL = ""
                            # URL = request.build_absolute_uri(URL)
                        receiver = new_reimb.pos  # 通知接收者
                        new_notification = notification_create(
                            receiver,
                            request.user,
                            typename,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )

                        en_pw = hash_coder.encode(
                            str(new_reimb.id) + "新建报销" + str(new_notification.id)
                        )
                        URL = "/addReimbursement?reimb_id={id}&notifi_id={nid}&enpw={en_pw}".format(
                            id=new_reimb.id, nid=new_notification.id, en_pw=en_pw
                        )
                        # URL = request.build_absolute_uri(URL)
                        new_notification.URL = URL
                        new_notification.save()
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())
                if notification_id != -1:
                    context = notification_status_change(notification_id)  # 修改通知状态
                # 成功发送通知
                html_display["warn_code"] = 2
                html_display["warn_message"] = "该组织的经费申请已通过！"
                if context["warn_code"] != 2:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] += context["warn_message"]
                # 微信通知
                publish_notification(new_notification)

            elif submit == 3:  # 拒绝
                try:  # 发送给申请者的拒绝通知
                    with transaction.atomic():
                        new_reimb.status = Reimbursement.ReimburseStatus.REFUSED
                        new_reimb.save()
                        content = "很遗憾，{act_name}报销申请未通过！".format(
                            act_name=new_reimb.activity.title
                        )
                        receiver = new_reimb.pos  # 通知接收者
                        URL = "/showReimbursement/"  # 报销失败可能应该鼓励继续报销
                        # URL = request.build_absolute_uri(URL)
                        new_notification = notification_create(
                            receiver,
                            request.user,
                            Notification.Type.NEEDREAD,
                            Notification.Title.VERIFY_INFORM,
                            content,
                            URL,
                        )

                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "创建发送给申请者的通知失败。请联系管理员！"
                    return render(request, "reimbursement_comment.html", locals())
                if notification_id != -1:
                    context = notification_status_change(
                        notification_id, Notification.Status.DONE
                    )
                # 拒绝成功
                html_display["warn_code"] = 2
                html_display["warn_message"] = "已成功拒绝该组织的经费申请！"
                if context["warn_code"] == 1:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = context["warn_message"]
                # 微信通知
                publish_notification(new_notification)
            else:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "出现未知参数，请联系管理员"
                return redirect(
                    "/notifications/"
                    + "?warn_code={}&warn_message={}".format(
                        html_display["warn_code"], html_display["warn_message"]
                    )
                )

    if new_reimb.status not in TERMINATE_STATUSES:  # 正在申请中，可以评论。
        commentable = 1  # 可以评论
    if new_reimb.status in TERMINATE_STATUSES and notification.status == Notification.Status.UNDONE:
        # 未读变已读
        notification_status_change(notification_id, Notification.Status.DONE)
    comments = showComment(new_reimb)  # 加载评论
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "报销审核"
    bar_display["navbar_name"] = "报销审核"
    return render(request, "reimbursement_comment.html", locals())
    bar_display["title_name"] = "报销审核"
    bar_display["navbar_name"] = "报销审核"
    return render(request, "reimbursement_comment.html", locals())
    bar_display["title_name"] = "报销审核"
    bar_display["navbar_name"] = "报销审核"
    return render(request, "reimbursement_comment.html", locals())


# 对一个已经完成的申请, 构建相关的通知和对应的微信消息, 将有关的事务设为已完成
# 如果有错误，则不应该是用户的问题，需要发送到管理员处解决
def make_relevant_notification(application, info):
    
    # 考虑不同post_type的信息发送行为
    post_type = info.get("post_type")
    print(post_type)
    feasible_post = ["new_submit", "modify_submit", "cancel_submit", "accept_submit", "refuse_submit"]
    
    # 准备呈现使用的变量与信息

    # 先准备一些复杂变量
    try:
        position_name = application.org.otype.get_name(application.pos)  # 职位名称
    except:
        position_name = "退出组织"

    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    content = {
        'new_submit':f'{application.person.name}发起组织人事变动申请，人事申请：{position_name}，请审核~',
        'modify_submit':f'{application.person.name}修改了组织申请信息，请审核~',
        'cancel_submit':f'{application.person.name}取消了组织申请信息。',
        'accept_submit':f'恭喜，您申请的组织：{application.org.oname}，审核已通过！申请职位：{position_name}。',
        'refuse_submit':f'抱歉，您申请的组织：{application.org.oname}，审核未通过！申请职位：{position_name}。',
    }
    sender = application.person.person_id if feasible_post.index(post_type) < 3 else application.org.organization_id
    receiver = application.org.organization_id if feasible_post.index(post_type) < 3 else application.person.person_id
    typename = Notification.Type.NEEDDO if  post_type == 'new_submit' else Notification.Type.NEEDREAD
    title = Notification.Title.VERIFY_INFORM if post_type != 'accept_submit' else Notification.Title.POSITION_INFORM
    URL = f'/modifyPosition/?pos_id={application.id}'
    relate_instance = application if post_type == 'new_submit' else None
    publish_to_wechat = True
    # TODO cancel是否要发送notification？是否发送微信？

    # 正式创建notification
    notification_create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content[post_type],
        URL=URL,
        relate_instance=relate_instance,
        publish_to_wechat=publish_to_wechat
    )

    # 对于处理类通知的完成(done)，修改状态
    # 这里的逻辑保证：所有的处理类通知的生命周期必须从“人事发起”开始，从“取消”“通过”“拒绝”结束。
    if feasible_post.index(post_type) >= 2:
        notification_status_change(
            application.relate_notifications.get(status=Notification.Status.UNDONE).id
        )