from django.dispatch.dispatcher import NO_RECEIVERS, receiver
from django.template.defaulttags import register
from app.models import (
    NaturalPerson,
    Freshman,
    Position,
    Organization,
    OrganizationType,
    Position,
    ModifyPosition,
    Activity,
    ActivityPhoto,
    TransferRecord,
    Participant,
    Notification,
    ModifyOrganization,
    Comment,
    CommentPhoto,
    YQPointDistribute,
    Reimbursement,
    Wishes,
)
import app.utils as utils
from app.forms import UserForm
from app.utils import (
    url_check, 
    check_cross_site, 
    get_person_or_org, 
    update_org_application, 
    wrong, 
    succeed,
)
from app.activity_utils import (
    create_activity,
    modify_activity,
    accept_activity,
    reject_activity,
    applyActivity,
    cancel_activity,
    withdraw_activity,
    ActivityException,
    get_activity_QRcode,
)
from app.position_utils import(
    update_pos_application,
)
from app.reimbursement_utils import update_reimb_application
from app.wechat_send import(
    publish_notification,
    publish_notifications,
    send_wechat_captcha,
    invite,
)
from app.notification_utils import(
    notification_create,
    bulk_notification_create,
    notification_status_change,
)
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
from datetime import date, datetime, timedelta
from urllib import parse, request as urllib2
import qrcode
import random
import requests  # 发送验证码
import io
import csv
import os

# 定时任务不在views直接调用

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
                pass # 现在统一放到下面处理，这里只负责登录
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

    # 所有跳转，现在不管是不是post了
    if arg_origin is not None:
        if request.user.is_authenticated:

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

            timeStamp = str(int(datetime.utcnow().timestamp())) # UTC 统一服务器
            username = request.session["username"]
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
        oneself_orgs_id = [oneself.id] if user_type == "Organization" else oneself_orgs.values("id") # 自己的组织

        # 管理的组织
        person_owned_poss = person_poss.filter(pos=0, status=Position.Status.INSERVICE)
        person_owned_orgs = person_orgs.filter(
            id__in=person_owned_poss.values("org")
        )  # ta管理的组织
        person_owned_orgs_ava = [
            # utils.get_user_ava(org, "organization") for org in person_owned_orgs
            org.get_user_ava() for org in person_owned_orgs
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
            org.get_user_ava() for org in person_joined_orgs
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
            # utils.get_user_ava(org, "organization") for org in person_hidden_orgs
            org.get_user_ava() for org in person_hidden_orgs
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
            activity.start.strftime("%Y-%m-%d %H:%M") for activity in activities
        ]
        activities_end = [
            activity.end.strftime("%Y-%m-%d %H:%M") for activity in activities
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

        context["avatar_path"] = person.get_user_ava()
        context["wallpaper_path"] = utils.get_user_wallpaper(person, "Person")

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display
        bar_display = utils.get_sidebar_and_navbar(
            request.user, navbar_name="个人主页", title_name=(name + " | 元培成长档案")
            )
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
            urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=找不到对应团队,请联系管理员!"
            return redirect(urls)
        try:
            position = Position.objects.activated().filter(org=org, person=me)
            assert len(position) == 1
            position = position[0]
            assert position.pos == 0
        except:
            urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=没有登录到该团队账户的权限!"
            return redirect(urls)
        # 到这里,是本人组织并且有权限登录
        auth.logout(request)
        auth.login(request, org.organization_id)  # 切换到组织账号
        if org.first_time_login:
            return redirect("/modpw/")
        return redirect("/orginfo/?warn_code=2&warn_message=成功切换到"+str(org)+"的账号!")

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def user_login_org(request, org):
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)

    try:
        me = NaturalPerson.objects.activated().get(person_id=user)
    except:  # 找不到合法的用户
        return wrong("您没有权限访问该网址！请用对应团队账号登陆。")
    #是组织一把手
    try:
        position = Position.objects.activated().filter(org=org, person=me)
        assert len(position) == 1
        position = position[0]
        assert position.pos == 0
    except:
        urls = "/stuinfo/" + me.name + "?warn_code=1&warn_message=没有登录到该团队账户的权限!"
        return redirect(urls)
    # 到这里,是本人组织并且有权限登录
    auth.logout(request)
    auth.login(request, org.organization_id)  # 切换到组织账号
    return succeed("成功切换到团队账号处理该事务，建议事务处理完成后退出团队账号。")




@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def orginfo(request, name=None):
    """
        orginfo负责呈现组织主页，逻辑和stuinfo是一样的，可以参考
        只区分自然人和法人，不区分自然人里的负责人和非负责人。任何自然人看这个组织界面都是【不可管理/编辑组织信息】
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)

    if not valid:
        return redirect("/logout/")

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

    # 判断是否为组织账户本身在登录
    html_display["is_myself"] = me == org

    organization_name = name
    organization_type_name = org.otype.otype_name
    org_avatar_path = org.get_user_ava()
    wallpaper_path = utils.get_user_wallpaper(org, "Organization")
    # org的属性 YQPoint 和 information 不在此赘述，直接在前端调用

    if request.method == "POST" :
        if request.POST.get("export_excel") is not None and html_display["is_myself"]:
            html_display["warn_code"] = 2
            html_display["warn_message"] = "下载成功!"
            return utils.export_orgpos_info(org)

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
        if p.show_post == True or p.pos == 0 or html_display["is_myself"]:
            member = {}
            member['show_post'] = p.show_post
            member['id'] = p.id
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
        html_display["warn_message"] = "修改团队信息成功!"

    # 补充左边栏信息

    

    # 再处理修改信息的回弹
    modpw_status = request.GET.get("modinfo", None)
    html_display["modpw_code"] = modpw_status is not None and modpw_status == "success"


    # 组织活动的信息

    # 补充一些呈现信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="团队主页", title_name=org.oname + " | 元培成长档案")
    
    # 转账后跳转
    origin = request.get_full_path()

    # 补充订阅该组织的按钮
    allow_unsubscribe = org.otype.allow_unsubscribe # 是否允许取关
    is_person = True if user_type == "Person" else False
    if is_person:
        subscribe_flag = True if (
            organization_name not in me.unsubscribe_list.values_list("oname", flat=True)) \
            else False
    
    # 补充作为组织成员，选择是否展示的按钮
    show_post_change_button = False     # 前端展示“是否不展示我自己”的按钮，若为True则渲染这个按钮
    if user_type == 'Person':
        my_position = Position.objects.activated().filter(org=org, person=me).exclude(pos=0)
        if len(my_position):
            show_post_change_button = True
            my_position = my_position[0]
    

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

    nowtime = datetime.now()
    # 今天第一次访问 welcome 界面，积分加 0.5
    if is_person:
        with transaction.atomic():
            np = NaturalPerson.objects.select_for_update().get(person_id=request.user)
            if np.last_time_login is None or np.last_time_login.date() != nowtime.date():
                np.last_time_login = nowtime
                np.bonusPoint += 0.5
                np.save()

    # 开始时间在前后一周内，除了取消和审核中的活动。按时间逆序排序
    recentactivity_list = Activity.objects.get_recent_activity()

    # 开始时间在今天的活动,且不展示结束的活动。按开始时间由近到远排序
    activities = Activity.objects.get_today_activity()
    activities_start = [
        activity.start.strftime("%H:%M") for activity in activities
    ]
    html_display['today_activities'] = list(zip(activities, activities_start)) or None

    # 最新一周内发布的活动，按发布的时间逆序
    newlyreleased_list = Activity.objects.get_newlyreleased_activity()

    # 即将截止的活动，按截止时间正序
    prepare_times = Activity.EndBeforeHours.prepare_times
    signup_rec = Activity.objects.activated().filter(status = Activity.Status.APPLYING)
    signup_list = []
    for act in signup_rec:
        deadline = act.start - timedelta(hours=prepare_times[act.endbefore])
        dictmp = {}
        dictmp["deadline"] = deadline
        dictmp["act"] = act
        signup_list.append(dictmp)
    signup_list.sort(key=lambda x:x["deadline"])
    signup_list=signup_list[:10]
    # 如果提交了心愿，发生如下的操作
    if request.method == "POST" and request.POST:
        wishtext = request.POST.get("wish")
        background = ""
        if request.POST.get("backgroundcolor") is not None:
            bg = request.POST["backgroundcolor"]
            try:
                assert len(bg) == 7 and bg[0] == "#"
                int(bg[1:], base=16)
                background = bg
            except:
                print(f"心愿背景颜色{bg}不合规")
        new_wish = Wishes.objects.create(text = wishtext, background = background)
        new_wish.save()

    # 心愿墙！！！！!最近一周的心愿，已经逆序排列，如果超过100个取前100个就可
    wishes = Wishes.objects.filter(
        time__gt = nowtime-timedelta(days = 7)
    )
    wishes = wishes[:100]

    # 心愿墙背景图片
    colors = [
        "#FDAFAB","#FFDAC1","#FAF1D6",
        "#B6E3E9","#B5EAD7","#E2F0CB"
    ]
    backgroundpics = [{"src":"/static/assets/img/backgroundpics/"+str(i+1)+".png","color": colors[i] } for i in range(6)]
    paths = [
        "notifications","stuinfo","orginfo","user_account_setting"
    ]
    guidepics = ["/static/assets/img/guidepics/"+paths[i]+".jpeg" for i in range(4)]

    """ 
        取出过去一周的所有活动，filter出上传了照片的活动，从每个活动的照片中随机选择一张
        如果列表为空，那么添加一张default，否则什么都不加。
    """
    photo_display = []
    newlyended_activity = Activity.objects.get_newlyended_activity()
    for act in newlyended_activity:
        summaryphotos = act.photos.filter(type = ActivityPhoto.PhotoType.SUMMARY)
        if len(summaryphotos)>0:
            photo_display.append(summaryphotos[0]) # 朴素的随机
    for photo in photo_display:
        if str(photo.image)[0] == 'a': # 不是static静态文件夹里的文件，而是上传到media/activity的图片
            photo.image = settings.MEDIA_URL + str(photo.image)
    
    if len(photo_display)==0: # 这个分类是为了前端显示的便利，就不采用append了
        homepagephoto = "/static/assets/img/taskboard.jpg"
    else:
        firstpic = photo_display[0]
        photos = photo_display[1:]

    # 天气
    # weather = urllib2.urlopen("http://www.weather.com.cn/data/cityinfo/101010100.html").read()
    try:
        with open("weather.json") as weather_json:
            html_display['weather'] = json.load(weather_json)
    except:
        from app.scheduler_func import get_weather
        html_display['weather'] = get_weather()
    
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "元培生活")
    # bar_display["title_name"] = "Welcome Page"
    # bar_display["navbar_name"] = "元培生活"

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
    bar_display = utils.get_sidebar_and_navbar(request.user, "信息与隐私")
    # bar_display["title_name"] = "Account Setting"
    # bar_display["navbar_name"] = "账户设置"
    # bar_display["help_message"] = local_dict["help_message"]["账户设置"]

    if user_type == "Person":
        info = NaturalPerson.objects.filter(person_id=user)
        userinfo = info.values()[0]

        useroj = NaturalPerson.objects.get(person_id=user)

        former_wallpaper = utils.get_user_wallpaper(me, "Person")

        # print(json.loads(request.body.decode("utf-8")))
        if request.method == "POST" and request.POST:

            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(request, user_type)
            attr_check_list = [attr for attr in attr_dict.keys() if attr not in ['gender', 'ava', 'wallpaper']]
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
                useroj.avatar = attr_dict['ava']
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
        former_wallpaper = utils.get_user_wallpaper(me, "Organization")
        if request.method == "POST" and request.POST:

            ava = request.FILES.get("avatar")
            wallpaper=request.FILES.get("wallpaper")
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
            expr += bool(wallpaper)
            if wallpaper is not None:
                useroj.wallpaper = wallpaper
            useroj.save()
            avatar_path = settings.MEDIA_URL + str(ava)
            if expr >= 1:
                upload_state = True
                return redirect("/orginfo/?modinfo=success")
            # else: 没有更新

        return render(request, "org_account_setting.html", locals())


def freshman(request):
    if request.user.is_authenticated:
        return redirect("/welcome/")

    if request.GET.get("success") is not None:
        alert = request.GET.get("alert")
        return render(request, "registerSuccess.html", locals())

    # 选择生源地列表，前端使用量
    address_set = set(Freshman.objects.all().values_list("place", flat=True))
    address_set.discard("")
    address_set.discard("其它")
    address_list = sorted(address_set)
    address_list.append("其它")
    html_path = "freshman-top.html"
    if request.method == "POST":
        # 这些也是失败时的前端使用量
        try:
            sid = request.POST["sid"]
            sname = request.POST["sname"]
            gender = request.POST["gender"]
            birthday = request.POST["birthday"] # 前端使用
            birthplace = request.POST["birthplace"]
            email = request.POST["email"]
        except:
            err_msg = "提交信息不足"
            return render(request, html_path, locals())
        try:
            sid = str(sid)
            freshman = Freshman.objects.get(sid=sid)
        except:
            err_msg = "不存在该学号信息，你真的是新生吗？"
            return render(request, html_path, locals())
        try:
            exist = freshman.exists()
            assert exist != "user", "用户仅部分注册，请联系管理员"
            registered = freshman.status == Freshman.Status.REGISTERED
            assert not (exist and not registered), "您尚未注册，但用户已存在，请联系管理员"
            assert not (not exist and registered), "您已经注册，但用户不存在，请联系管理员"
            if exist or registered:
                err_msg = "您的账号已被注册过，请阅读使用说明！"
                return redirect("/freshman/?success=1&alert=" + err_msg)
        except Exception as e:
            err_msg = str(e)
            return render(request, html_path, locals())
        try:
            sname = str(sname)
            gender = str(gender)
            birthday_date = datetime.strptime(birthday, "%Y-%m-%d").date()
            birthplace = str(birthplace)
            email = str(email)
        except:
            err_msg = "错误的个人信息格式"
            return render(request, html_path, locals())
        try:
            assert freshman.name == sname, "姓名不匹配"
            assert freshman.gender == gender, "个人信息错误"
            assert freshman.birthday == birthday_date, "个人信息错误"
            if freshman.place != "":
                assert freshman.place == birthplace, "生源地错误"
            else:
                assert "其它" == birthplace, "生源地错误"
            assert "@" in email, "请使用合法的邮件地址"
            assert gender in ["男", "女"], "性别数据异常，请联系管理员"
        except Exception as e:
            err_msg = str(e)
            return render(request, html_path, locals())

        np_gender = NaturalPerson.Gender.MALE if gender == "男" else\
                    NaturalPerson.Gender.FEMALE

        # 检查通过，这里假设user创建成功后自然人也能创建成功
        current = "随机生成密码"
        try:
            with transaction.atomic():
                password = hash_coder.encode(sname + str(random.random()))
                current = "创建用户"
                user = User.objects.create_user(username=sid, password=password)
                current = "创建个人账号"
                NaturalPerson.objects.create(
                    person_id=user,
                    stu_id_dbonly=sid,
                    name=sname,
                    gender=np_gender,
                    stu_major="元培计划（待定）",
                    stu_grade=freshman.grade,
                    email=email,
                    )
                current = "更新注册状态"
                Freshman.objects.filter(sid=sid).select_for_update().update(
                    status = Freshman.Status.REGISTERED)
        except:
            err_msg = f"在{current}时意外发生了错误，请联系管理员"
            return render(request, html_path, locals())
        
        # 发送企业微信邀请，不会报错
        invite(sid, multithread=True)
        
        err_msg = "您的账号已成功注册，请尽快加入企业微信以接受后续通知！"
        return redirect("/freshman/?success=1&alert=" + err_msg)

    return render(request, html_path, locals())


def auth_register(request):
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
            stu = NaturalPerson.objects.get(person_id__username=stuId)
            img_path = stu.get_user_ava()
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

    now = datetime.now()
    def get_recent_activity(org):
        activities = Activity.objects.activated().filter(Q(organization_id=org.id)
                                                         & ~Q(status=Activity.Status.CANCELED)
                                                         & ~Q(status=Activity.Status.REJECT))
        activities = list(activities)
        activities.sort(key=lambda activity: abs(now - activity.start))
        return None if len(activities) == 0 else activities[0:3]

    org_display_list = []
    for org in organization_list:
        org_display_list.append(
            {
                "oname": org.oname,
                "otype": org.otype,
                "pos0": NaturalPerson.objects.activated().filter(
                    id__in=Position.objects.activated().filter(pos=0, org=org).values("person")
                ),  #TODO:直接查到一个NaturalPerson的Query_set
                # [
                #     w["person__name"]
                #     for w in list(
                #         org.position_set.activated()
                #             .filter(pos=0)
                #             .values("person__name")
                #     )
                # ],
                "activities": get_recent_activity(org),
                "get_user_ava": org.get_user_ava()
            }
        )

    # 组织要呈现的具体内容
    organization_field = ["组织名称", "组织类型", "负责人", "近期活动"]

    # 搜索活动
    activity_list = Activity.objects.filter(
        Q(title__icontains=query) | Q(organization_id__oname__icontains=query)& ~Q(status=Activity.Status.CANCELED)
                                                         & ~Q(status=Activity.Status.REJECT)
        &~Q(status=Activity.Status.REVIEWING)&~Q(status=Activity.Status.ABORT)
    )

    # 活动要呈现的内容
    activity_field = ["活动名称", "承办组织", "状态"]

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "信息搜索")
    # bar_display["title_name"] = "Search"
    # bar_display["navbar_name"] = "信息搜索"  #

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
            - 消息提示现在与整体统一
            - 添加`alert`表示需要提醒
            - 添加`noshow`不在页面显示文字
        - 尝试发送验证码后总是弹出提示框，通知用户验证码的发送情况
        
        注意事项
        -------
        - 尝试忘记密码的不一定是本人，一定要做好隐私和逻辑处理
            - 用户邮箱应当部分打码，避免向非本人提供隐私数据！
        - 连接设置的timeout为6s
        - 如果引入企业微信验证，建议将send_captcha分为'qywx'和'email'
    """
    if request.user.is_authenticated:
        return redirect("/welcome/")

    if request.session.get("received_user"):
        username = request.session["received_user"]  # 自动填充，方便跳转后继续
    if request.method == "POST":
        username = request.POST["username"]
        send_captcha = request.POST["send_captcha"]
        vertify_code = request.POST["vertify_code"]  # 用户输入的验证码

        user = User.objects.filter(username=username)
        if not user:
            display = wrong("账号不存在")
        elif len(user) != 1:
            display = wrong("用户名不唯一，请联系管理员")
        else:
            user = user[0]
            try:
                person = NaturalPerson.objects.get(person_id=user)  # 目前只支持自然人
            except:
                display = wrong("暂不支持组织账号验证码登录！")
                display["alert"] = True
                return render(request, "forget_password.html", locals())
            if send_captcha in ["yes", "email"]:    # 单个按钮(yes)发送邮件
                email = person.email
                if not email or email.lower() == "none" or "@" not in email:
                    display = wrong(
                            "您没有设置邮箱，请联系管理员"
                            + "或发送姓名、学号和常用邮箱至gypjwb@pku.edu.cn进行修改"
                    )  # TODO:记得填
                else:
                    captcha = utils.get_captcha(request, username)
                    msg = (
                            f"<h3><b>亲爱的{person.name}同学：</b></h3><br/>"
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
                            display = wrong(f"未能向{pre}@{suf}发送邮件")
                            print("向邮箱api发送失败，原因：", response["data"]["errMsg"])
                        else:
                            # 记录验证码发给谁 不使用username防止被修改
                            utils.set_captcha_session(request, username, captcha)
                            display = succeed(f"验证码已发送至{pre}@{suf}")
                            display["noshow"] = True
                    except:
                        display = wrong("邮件发送失败：超时")
                    finally:
                        display["alert"] = True
                        display.setdefault("colddown", 60)
            elif send_captcha in ["wechat"]:    # 发送企业微信消息
                username = person.person_id.username
                captcha = utils.get_captcha(request, username)
                send_wechat_captcha(username, captcha)
                display = succeed(f"验证码已发送至企业微信")
                display["noshow"] = True
                display["alert"] = True
                utils.set_captcha_session(request, username, captcha)
                display.setdefault("colddown", 60)
            else:
                captcha, expired, old = utils.get_captcha(request, username, more_info=True)
                if not old:
                    display = wrong("请先发送验证码")
                elif expired:
                    display = wrong("验证码已过期，请重新发送")
                elif str(vertify_code).upper() == captcha.upper():
                    auth.login(request, user)
                    utils.clear_captcha_session(request)
                    request.session["username"] = username
                    request.session["forgetpw"] = "yes"
                    return redirect(reverse("modpw"))
                else:
                    display = wrong("验证码错误")
                display.setdefault("colddown", 30)
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
        strict_check = True

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
    bar_display = utils.get_sidebar_and_navbar(request.user, "修改密码")
    # 补充一些呈现信息
    # bar_display["title_name"] = "Modify Password"
    # bar_display["navbar_name"] = "修改密码"
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
    html_display['warn_code'] = 0

    try:
        user = User.objects.get(id=rid)
        recipient = utils.get_person_or_org(user)

    except:
        return redirect(
            "/welcome/?warn_code=1&warn_message=该用户不存在，无法实现转账!")
    if not hasattr(recipient, "organization_id") or user_type != "Organization":
        html_display = wrong("目前只支持组织向组织转账！")
    if request.user == user:
        html_display=wrong("不能向自己转账！")
    if html_display['warn_code']==1:
        if hasattr(recipient, "organization_id"):
            return redirect(
                "/orginfo/{name}?warn_code=1&warn_message={message}".format(name=recipient.oname,
                                                                                      message=html_display[
                                                                                          'warn_message']))
        else:
            return  redirect(
                "/stuinfo/{name}?warn_code=1&warn_message={message}".format(name=recipient.name,
                                                                            message=html_display['warn_message']))
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 如果希望前移，请联系YHT
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Transaction"
    bar_display["navbar_name"] = "发起转账"

    # 获取名字
    _, _, context = utils.check_user_type(user)
    context = utils.get_sidebar_and_navbar(user, bar_display=context)
    name = recipient.oname
    context["name"] = name
    context["rid"] = rid
    context["YQPoint"] = me.YQPoint

    # 如果是post, 说明发起了一起转账
    # 到这里, rid没有问题, 接收方和发起方都已经确定
    if request.method == "POST":
        # 获取转账消息, 如果没有消息, 则为空
        transaction_msg = request.POST.get("msg", "")

        # 检查发起转账的数据
        try:
            amount = float(request.POST["amount"])
            assert amount > 0
            assert int(amount * 10) == amount * 10
        except:
            return redirect("/welcome/")

        # 到这里, 参数的合法性检查完成了, 接下来应该是检查发起人的账户, 够钱就转
        try:
            with transaction.atomic():
                # 首先锁定用户
                payer = (
                    Organization.objects.activated()
                        .select_for_update()
                        .get(organization_id=request.user)
                )

                # 接下来确定金额
                if payer.oname != "元培学院" and payer.YQPoint < amount:
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
                    return redirect("/myYQPoint/")

        except Exception as e:
            # print(e)
            html_display["warn_code"] = 1
            html_display["warn_message"] = "出现无法预料的问题, 请联系管理员!"


    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 如果希望前移，请联系YHT
    bar_display = utils.get_sidebar_and_navbar(request.user)
    bar_display["title_name"] = "Transaction"
    bar_display["navbar_name"] = "发起转账"
    return render(request, "transaction_page.html", locals())



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
        lis[-1]["start_time"] = record.start_time.strftime("%Y-%m-%d %H:%M")
        if record.finish_time is not None:
            lis[-1]["finish_time"] = record.finish_time.strftime("%Y-%m-%d %H:%M")

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
    if user_type == "Person":
        quota_and_YQPoint = me.YQPoint + me.quota
    else:
        quota_and_YQPoint = me.YQPoint

    show_table = {
        "obj": "对象",
        "time": "时间",
        "amount": "金额",
        "message": "留言",
        "status": "状态",
    }

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "我的元气值")
    # 补充一些呈现信息
    # bar_display["title_name"] = "My YQPoint"
    # bar_display["navbar_name"] = "我的元气值"  #
    # bar_display["help_message"] = local_dict["help_message"]["我的元气值"]

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
        org = activity.organization_id
        me = utils.get_person_or_org(request.user, user_type)
        ownership = False
        if user_type == "Organization" and org == me:
            ownership = True
        examine = False
        if user_type == "Person" and activity.examine_teacher == me:
            examine = True
        if not (ownership or examine):
            assert activity.status != Activity.Status.REVIEWING
            assert activity.status != Activity.Status.ABORT
            assert activity.status != Activity.Status.REJECT
    except Exception as e:
        # print(e)
        return redirect("/welcome/")

    html_display = dict()

    if request.method == "POST" and request.POST:
        option = request.POST.get("option")
        if option == "cancel":
            try:
                assert activity.status != Activity.Status.REJECT
                assert activity.status != Activity.Status.ABORT
                assert activity.status != Activity.Status.END
                assert activity.status != Activity.Status.CANCELED
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=aid)
                    cancel_activity(request, activity)
                    html_display["warn_code"] = 2
                    html_display["warn_message"] = "成功取消活动。"
            except ActivityException as e:
                html_display["warn_code"] = 1
                html_display["warn_message"] = str(e)
                print("GOTCHA")
            except:
                redirect("/welcome/")

        elif option == "edit":
            if (
                    activity.status == activity.Status.APPLYING
                    or activity.status == activity.Status.REVIEWING
            ):
                return redirect(f"/editActivity/{aid}")
            if activity.status == activity.Status.WAITING:
                if activity.start + timedelta(hours=1) < datetime.now():
                    return redirect(f"/editActivity/{aid}")
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"活动即将开始, 不能修改活动。"
            else:
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"活动状态为{activity.status}, 不能修改。"

        elif option == "apply":
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=int(aid))
                    assert activity.status == Activity.Status.APPLYING
                    applyActivity(request, activity)
                    if activity.bidding:
                        html_display["warn_message"] = f"活动申请中，请等待报名结果。"
                    else:
                        html_display["warn_message"] = f"报名成功。"
                    html_display["warn_code"] = 2
            except ActivityException as e:
                html_display["warn_code"] = 1
                html_display["warn_message"] = str(e)
            except:
                redirect('/welcome/')


        elif option == "quit":
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=aid)
                    assert (
                            activity.status == Activity.Status.APPLYING
                            or activity.status == Activity.Status.WAITING
                    )
                    withdraw_activity(request, activity)
                    if activity.bidding:
                        html_display["warn_message"] = f"已取消申请。"
                    else:
                        html_display["warn_message"] = f"已取消报名。"
                    html_display["warn_code"] = 2

            except ActivityException as e:
                html_display["warn_code"] = 1
                html_display["warn_message"] = str(e)
            except:
                return redirect('/welcome/')

        elif option == "payment":
            try:
                assert activity.status == Activity.Status.END
                assert ownership
                re = Reimbursement.objects.get(related_activity=activity)
                return redirect(f"/modifyReimbursement/?reimb_id={re.id}")
            except Exception as e:
                # print("Exception", e)
                return redirect("/modifyReimbursement/")

        elif option == "submitphoto":
            if not (ownership and activity.status == Activity.Status.END):
                return redirect("/welcome/")

            summary_photo_exists = False
            if activity.status == Activity.Status.END:
                try:
                    summary_photo = activity.photos.get(type=ActivityPhoto.PhotoType.SUMMARY)
                    summary_photo_exists = True
                except:
                    pass
            try:
                summaryphotos = request.FILES.getlist('images')
                photo = summaryphotos[0]
            except:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "上传活动照片不能为空"
            if utils.if_image(photo) !=2:
                html_display['warn_code'] = 1
                html_display['warn_message'] = "上传的附件只支持图片格式"
            elif summary_photo_exists:
                old_photo = activity.photos.get(type=ActivityPhoto.PhotoType.SUMMARY)
                old_photo.image = photo
                old_photo.save()
                summary_photo = settings.MEDIA_URL + str(old_photo.image)
                html_display["warn_message"] = "成功替换活动照片"
            else:
                ActivityPhoto.objects.create(
                    image=photo, 
                    activity=activity, 
                    time=datetime.now(),
                    type = ActivityPhoto.PhotoType.SUMMARY
                )
                html_display["warn_message"] = "成功提交活动照片"
            html_display["warn_code"] = 2
        elif option == "download":
            return utils.export_activity_signin(activity)
        else:
            return redirect("/welcome")


    # 下面这些都是展示前端页面要用的
    title = activity.title
    org_name = org.oname
    org_avatar_path = org.get_user_ava()
    org_type = OrganizationType.objects.get(otype_id=org.otype_id).otype_name
    start_time = activity.start.strftime("%Y-%m-%d %H:%M")
    end_time = activity.end.strftime("%Y-%m-%d %H:%M")
    start_THEDAY = activity.start.day # 前端使用量
    prepare_times = Activity.EndBeforeHours.prepare_times
    apply_deadline = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    introduction = activity.introduction
    show_url = True # 前端使用量
    aURL = activity.URL
    if (aURL is None) or (aURL == ""):
        show_url = False
    bidding = activity.bidding
    price = activity.YQPoint
    from_student = activity.source == Activity.YQPointSource.STUDENT
    current_participants = activity.current_participants
    status = activity.status
    capacity = activity.capacity
    if capacity == -1 or capacity == 10000:
        capacity = "INF"
    if activity.source == Activity.YQPointSource.COLLEGE:
        price = 0
    if activity.bidding:
        apply_manner = "抽签模式"
    else:
        apply_manner = "先到先得"
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

    # 签到
    need_checkin = activity.need_checkin
    show_QRcode = activity.need_checkin and activity.status in [
        Activity.Status.APPLYING,
        Activity.Status.WAITING,
        Activity.Status.PROGRESSING
    ]

    if ownership and need_checkin:
        aQRcode = get_activity_QRcode(activity)

    # 活动宣传图片 ( 一定存在 )
    photo = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
    firstpic = str(photo.image)
    if firstpic[0] == 'a': # 不是static静态文件夹里的文件，而是上传到media/activity的图片
        firstpic = settings.MEDIA_URL + firstpic

    # 总结图片，不一定存在
    summary_photo_exists = False
    if activity.status == Activity.Status.END:
        try:
            summary_photo = activity.photos.get(type=ActivityPhoto.PhotoType.SUMMARY)
            summary_photo_exists = True
            summary_photo = settings.MEDIA_URL + str(summary_photo.image)
        except Exception as e:
            # print(e)
            pass

    # 新版侧边栏，顶栏等的呈现，采用bar_display，必须放在render前最后一步，但这里render太多了
    # TODO: 整理好代码结构，在最后统一返回
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="活动信息", title_name=(title + " | 元培成长档案"))
    # 补充一些呈现信息
    # bar_display["title_name"] = "活动信息"
    # bar_display["navbar_name"] = "活动信息"

    return render(request, "activity_info.html", locals())


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

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def checkinActivity(request, aid=None):
    valid, user_type, html_display = utils.check_user_type(request.user)
    try:
        assert user_type == "Person"
        np = get_person_or_org(request.user)
        activity = Activity.objects.get(id=int(aid))
        varifier = request.GET["auth"]
        assert varifier == hash_coder.encode(aid)
        assert activity.status == Activity.Status.PROGRESSING
    except:
        return redirect("/welcome/")
    try:
        with transaction.atomic():
            participant = Participant.objects.select_for_update().get(
                activity_id=int(aid), person_id=np,
                status=Participant.AttendStatus.UNATTENDED
            )
            participant.status = Participant.AttendStatus.ATTENDED
            participant.save()
    except:
        pass
    # TODO 在 activity_info 里加更多信息
    return redirect(f"/viewActivity/{aid}")


# participant checkin activity
# GET参数?activityid=id
#   activity_id : 活动id
# example: http://127.0.0.1:8000/checkinActivity?activityid=1
# TODO: 前端页面待对接
"""
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
"""


# TODO 定时任务
"""
发起活动与修改活动页
---------------
页面逻辑：

该函数处理 GET, POST 两种请求，发起和修改两类操作
1. 访问 /addActivity/ 时，为创建操作，要求用户是组织；
2. 访问 /editActivity/aid 时，为编辑操作，要求用户是该活动的发起者
3. GET 请求创建活动的界面，placeholder 为 prompt
4. GET 请求编辑活动的界面，表单的 placeholder 会被修改为活动的旧值。
"""

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def addActivity(request, aid=None):

    # 检查：不是超级用户，必须是组织，修改是必须是自己
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        assert valid
        me = utils.get_person_or_org(request.user, user_type) # 这里的me应该为组织账户
        if aid is None:
            assert user_type == "Organization"
            edit = False
        else:
            aid = int(aid)
            activity = Activity.objects.get(id=aid)
            if user_type == "Person":
                html_display=user_login_org(request,activity.organization_id)
                if html_display['warn_code']==1:
                    return redirect(
                        "/welcome/"
                        + "?warn_code={}&warn_message={}".format(
                            html_display["warn_code"], html_display["warn_message"]
                        )
                    )
                else:#成功以组织账号登陆
                    #防止后边有使用，因此需要赋值
                    user_type="Organization"
                    request.user=activity.organization_id.organization_id#组织对应user
                    me = activity.organization_id#组织
            assert activity.organization_id == me
            edit = True
        html_display["is_myself"] = True
    except Exception as e:
        print(e)
        return redirect("/welcome/")

    # 处理 POST 请求
    # 在这个界面，不会返回render，而是直接跳转到viewactivity，可以不设计bar_display
    if request.method == "POST" and request.POST:

        if not edit:
            try:
                with transaction.atomic():
                    aid = create_activity(request)
                    return redirect(f"/viewActivity/{aid}")
            except Exception as e:
                print(e)
                return redirect("/welcome/")

        # 仅这几个阶段可以修改
        if (
                activity.status != Activity.Status.REVIEWING and
                activity.status != Activity.Status.APPLYING and 
                activity.status != Activity.Status.WAITING
        ):
            return redirect("/welcome/")

        # 处理 comment
        if request.POST.get("comment_submit"):
            try:
                # 创建活动只能在审核时添加评论
                assert not activity.valid
                context = addComment(request, activity, activity.examine_teacher.person_id)
                # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
                assert context["warn_code"] == 2
                # 成功后重新加载界面
                html_display["warn_msg"] = "评论成功。"
                html_display["warn_code"] = 2
                # return redirect(f"/editActivity/{aid}")
            except Exception as e:
                print(e)
                return redirect("/welcome/")
        else:
            try:
                # 只能修改自己的活动
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=aid)
                    org = get_person_or_org(request.user, "Organization")
                    assert activity.organization_id == org
                    modify_activity(request, activity)
                html_display["warn_msg"] = "修改成功。"
                html_display["warn_code"] = 2
            except ActivityException as e:
                html_display["warn_msg"] = str(e)
                html_display["warn_code"] = 1
                # return redirect(f"/viewActivity/{activity.id}")
            except Exception as e:
                print(e)
                return redirect("/welcome/")

    # 下面的操作基本如无特殊说明，都是准备前端使用量
    defaultpics = [{"src":"/static/assets/img/announcepics/"+str(i+1)+".JPG","id": "picture"+str(i+1) } for i in range(5)]
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava() 
    if not edit:
        avialable_teachers = NaturalPerson.objects.teachers()
    else:
        try:
            org = get_person_or_org(request.user, "Organization")

            # 没过审，可以编辑评论区
            if not activity.valid:
                commentable = True
                front_check = True
            # 全可编辑
            full_editable = False
            accepted = False
            if activity.status == Activity.Status.REVIEWING:
                full_editable = True
                accepted = True
            # 部分可编辑
            # 活动只能在开始 1 小时前修改
            elif (
                    activity.status == Activity.Status.APPLYING
                    or activity.status == Activity.Status.WAITING
            ) and datetime.now() + timedelta(hours=1) < activity.start:
                accepted = True
            else:
                # 不是三个可以评论的状态
                commentable = front_check = False
        except Exception as e:
            print(e)
            return redirect("/welcome/")

        # 决定状态的变量
        # None/edit/examine ( 组织申请活动/组织编辑/老师审查 )
        # full_editable/accepted/None ( 组织编辑活动：除审查老师外全可修改/部分可修改/全部不可改 )
        #        full_editable 为 true 时，accepted 也为 true
        # commentable ( 是否可以评论 )

        # 下面是前端展示的变量
        title = activity.title
        budget = activity.budget
        location = activity.location
        start = activity.start.strftime("%Y-%m-%d %H:%M")
        end = activity.end.strftime("%Y-%m-%d %H:%M")
        apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
        introduction = activity.introduction
        url = activity.URL
        endbefore = activity.endbefore
        bidding = activity.bidding
        amount = activity.YQPoint
        signscheme = "先到先得"
        if bidding:
            signscheme = "抽签模式"
        capacity = activity.capacity
        yq_source = "向学生收取"
        if activity.source == Activity.YQPointSource.COLLEGE:
            yq_source = "向学院申请"
        no_limit = False
        if capacity == 10000:
            no_limit = True
        examine_teacher = activity.examine_teacher.name
        status = activity.status
        avialable_teachers = NaturalPerson.objects.filter(identity=NaturalPerson.Identity.TEACHER)
        need_checkin = activity.need_checkin
        apply_reason = activity.apply_reason
        comments = showComment(activity)
        photo = str(activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE).image)
        uploaded_photo = False
        if str(photo).startswith("activity"):
            uploaded_photo = True
            photo = os.path.basename(photo)
        else:
            photo_id = "picture" + os.path.basename(photo).split(".")[0]

    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    if not edit:
         bar_display = utils.get_sidebar_and_navbar(request.user, "活动发起")
    else:
         bar_display = utils.get_sidebar_and_navbar(request.user, "修改活动")

    return render(request, "activity_add.html", locals())

@login_required(redirect_field_name="origin")
def examineActivity(request, aid):
    valid, user_type, html_display = utils.check_user_type(request.user)
    try:
        assert valid
        assert user_type == "Person"
        me = utils.get_person_or_org(request.user)
        activity = Activity.objects.get(id=int(aid))
        assert activity.examine_teacher == me
    except:
        return redirect("/welcome/")

    html_display["is_myself"] = True

    if request.method == "POST" and request.POST:

        if (
                activity.status != Activity.Status.REVIEWING and
                activity.status != Activity.Status.APPLYING and
                activity.status != Activity.Status.WAITING
        ) or activity.valid:
            return redirect("/welcome/")


        if request.POST.get("comment_submit"):
            try:
                context = addComment(request, activity, activity.organization_id.organization_id)
                # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
                assert context["warn_code"] == 2
                html_display["warn_msg"] = "评论成功。"
                html_display["warn_code"] = 2
            except Exception as e:
                # print(e)
                return redirect("/welcome/")

        elif request.POST.get("review_accepted"):
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(
                        id=int(aid)
                    )
                    accept_activity(request, activity)
                html_display["warn_msg"] = "活动已通过。"
                html_display["warn_code"] = 2
            except Exception as e:
                # print(e)
                return redirect("/welcome/")
        else:
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(
                        id=int(aid)
                    )
                    reject_activity(request, activity)
                html_display["warn_msg"] = "活动已被拒绝。"
                html_display["warn_code"] = 2
            except Exception as e:
                print(e)
                return redirect("/welcome/")


    # 状态量，无可编辑量
    examine = True
    commentable = not activity.valid
    if (
            activity.status != Activity.Status.REVIEWING and
            activity.status != Activity.Status.APPLYING and
            activity.status != Activity.Status.WAITING
    ):
        commentable = False

    # 展示变量
    title = activity.title
    budget = activity.budget
    location = activity.location
    apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
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
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    # html_display["app_avatar_path"] = utils.get_user_ava(activity.organization_id,"Organization")h
    html_display["app_avatar_path"] = activity.organization_id.get_user_ava()
    html_display["applicant_name"] = activity.organization_id.oname
    bar_display = utils.get_sidebar_and_navbar(request.user)
    status = activity.status
    comments = showComment(activity)

    examine_pic = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
    if str(examine_pic.image)[0] == 'a': # 不是static静态文件夹里的文件，而是上传到media/activity的图片
        examine_pic.image = settings.MEDIA_URL + str(examine_pic.image)
    intro_pic = examine_pic.image

    need_checkin = activity.need_checkin
    apply_reason = activity.apply_reason

    bar_display = utils.get_sidebar_and_navbar(request.user, "活动审核")
    # bar_display["title_name"] = "审查活动"
    # bar_display["narbar_name"] = "审查活动"
    return render(request, "activity_add.html", locals())

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def subscribeOrganization(request):
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
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="我的订阅")
    # 补充一些呈现信息
    # bar_display["title_name"] = "Subscribe"
    # bar_display["navbar_name"] = "我的订阅"  #
    # bar_display["help_message"] = local_dict["help_message"]["我的订阅"]

    subscribe_url = reverse("save_subscribe_status")
    return render(request, "organization_subscribe.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def save_show_position_status(request):
    valid, user_type, html_display = utils.check_user_type(request.user)

    me = utils.get_person_or_org(request.user, user_type)
    params = json.loads(request.body.decode("utf-8"))
    
    with transaction.atomic():
        try:
            position = Position.objects.select_for_update().get(id=params["id"])
        except:
            return JsonResponse({"success":False})
        if params["status"]:
            position.show_post = True
        else:
            if len(Position.objects.filter(pos=0, org=position.org)) == 1 and position.pos==0:    #非法前端量修改
                return JsonResponse({"success":False})
            position.show_post = False
        position.save()
    return JsonResponse({"success": True})

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def save_subscribe_status(request):
    valid, user_type, html_display = utils.check_user_type(request.user)

    me = utils.get_person_or_org(request.user, user_type)
    params = json.loads(request.body.decode("utf-8"))
    
    with transaction.atomic():
        if "id" in params.keys():
            try:
                org = Organization.objects.get(organization_id__username=params["id"])
            except:
                return JsonResponse({"success":False})
            if params["status"]:
                me.unsubscribe_list.remove(org)
            else:
                if not org.otype.allow_unsubscribe: # 非法前端量修改
                    return JsonResponse({"success":False})
                me.unsubscribe_list.add(org)
        elif "otype" in params.keys():
            try:
                unsubscribed_list = me.unsubscribe_list.filter(
                    otype__otype_id=params["otype"]
                )
                org_list = Organization.objects.filter(otype__otype_id=params["otype"])
            except:
                return JsonResponse({"success":False})
            if params["status"]:  # 表示要订阅
                for org in unsubscribed_list:
                    me.unsubscribe_list.remove(org)
            else:  # 不订阅
                try:
                    otype = OrganizationType.objects.get(otype_id = params["otype"])
                except:
                    return JsonResponse({"success":False})
                if not otype.allow_unsubscribe: # 非法前端量修改
                    return JsonResponse({"success":False})
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
        # print(e)
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





def notification2Display(notification_list):
    lis = []
    # 储存这个列表中所有record的元气值的和
    for notification in notification_list:
        lis.append({})

        # id
        lis[-1]["id"] = notification.id

        # 时间
        lis[-1]["start_time"] = notification.start_time.strftime("%Y-%m-%d %H:%M")
        if notification.finish_time is not None:
            lis[-1]["finish_time"] = notification.finish_time.strftime("%Y-%m-%d %H:%M")

        # 留言
        lis[-1]["content"] = notification.content

        # 状态
        lis[-1]["status"] = notification.get_status_display()
        lis[-1]["URL"] = notification.URL
        lis[-1]["type"] = notification.get_typename_display()
        lis[-1]["title"] = notification.get_title_display()
        _, user_type, _ = utils.check_user_type(notification.sender)
        if user_type == "Organization":
            lis[-1]["sender"] = Organization.objects.get(
                organization_id__username=notification.sender.username
            ).oname
        else:
            lis[-1]["sender"] = NaturalPerson.objects.get(
                person_id__username=notification.sender.username
            ).name
    return lis


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
        post_args = json.loads(request.body.decode("utf-8"))
        try:
            notification_id = int(post_args['id'])
        except:
            html_display["warn_code"] = 1  # 失败
            html_display["warn_message"] = "请不要恶意发送post请求！"
            return JsonResponse({"success":False})
        try:
            Notification.objects.activated().get(id=notification_id, receiver=request.user)
        except:
            html_display["warn_code"] = 1  # 失败
            html_display["warn_message"] = "请不要恶意发送post请求！！"
            return JsonResponse({"success":False})
        if "cancel" in post_args['function']:
            try:
                notification_status_change(notification_id, Notification.Status.DELETE)
                html_display["warn_code"] = 2  # success
                html_display["warn_message"] = "您已成功删除一条通知！"
                return JsonResponse({"success":True})
            except:
                html_display["warn_code"] = 1  # 失败
                html_display["warn_message"] = "删除通知的过程出现错误！请联系管理员。"
                return JsonResponse({"success":False})
        else:
            try:
                context = notification_status_change(notification_id)
                html_display["warn_code"] = context["warn_code"]
                html_display["warn_message"] = context["warn_message"]
                return JsonResponse({"success":True})
            except:
                html_display["warn_code"] = 1  # 失败
                html_display["warn_message"] = "修改通知状态的过程出现错误！请联系管理员。"
                return JsonResponse({"success":False})

    me = utils.get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True
    
    notification_set = Notification.objects.activated().filter(receiver=request.user)

    done_list = notification2Display(
        list(notification_set.union(notification_set).order_by("-finish_time"))
    )

    undone_list = notification2Display(
        list(notification_set.union(notification_set).order_by("-start_time"))
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
    valid, user_type, html_display = utils.check_user_type(request.user)
    sender = utils.get_person_or_org(request.user)
    if user_type == "Organization":
        sender_name = sender.oname
    else:
        sender_name = sender.name
    context = dict()
    typename = comment_base.typename
    content = {
        'modifyposition': f'{sender_name}在人事变动申请留有新的评论',
        'neworganization': f'{sender_name}在新建组织中留有新的评论',
        'reimbursement': f'{sender_name}在经费申请中留有新的评论',
        'activity': f"{sender_name}在活动申请中留有新的评论"
    }
    URL={
        'modifyposition': f'/modifyPosition/?pos_id={comment_base.id}',
        'neworganization': f'/modifyOrganization/?org_id={comment_base.id}',
        'reimbursement': f'/modifyReimbursement/?reimb_id={comment_base.id}',
        'activity': f"/examineActivity/{comment_base.id}"
    }
    if user_type == "Organization":
        URL["activity"] = f"/editActivity/{comment_base.id}"
    if request.POST.get("comment_submit") is not None:  # 新建评论信息，并保存
        text = str(request.POST.get("comment"))
        # 检查图片合法性
        comment_images = request.FILES.getlist('comment_images')
        if text == "" and comment_images == []:
            context['warn_code'] = 1
            context['warn_message'] = "评论内容均为空，无法评论！"
            return context
        if len(comment_images) > 0:
            for comment_image in comment_images:
                if utils.if_image(comment_image)!=2:
                    context["warn_code"] = 1
                    context["warn_message"] = "评论中上传的附件只支持图片格式。"
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
            return context

        if len(text) > 0:
            content[typename] += f':{text}'
        else:
            content[typename] += "。"
        if len(text) >= 32:
            text = text[:31] + "……"
       
        if user_type == "Organization":
            URL["activity"] = f"/examineActivity/{comment_base.id}"
        else:
            URL["activity"] = f"/editActivity/{comment_base.id}"

        if receiver is not None:
            notification_create(
                receiver,
                request.user,
                Notification.Type.NEEDREAD,
                Notification.Title.VERIFY_INFORM,
                content[typename],
                URL[typename],
            )
        context["new_comment"] = new_comment
        context["warn_code"] = 2
        context["warn_message"] = "评论成功。"
    else:
        return wrong("找不到评论信息, 请重试!")
    return context


def showComment(commentbase):
    comments = commentbase.comments.order_by("time")
    for comment in comments:
        commentator = get_person_or_org(comment.commentator)
        if comment.commentator.username[:2] == "zz":
            comment.ava = commentator.get_user_ava()
            comment.URL = "/orginfo/{name}".format(name=commentator.oname)
            comment.commentator_name = commentator.oname
        else:
            comment.ava = commentator.get_user_ava()
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
    charge_org = ModifyOrganization.objects.filter(otype__in=me.incharge.all())

    # 拉去由我发起的申请，这部分等待审核
    applied_org = ModifyOrganization.objects.filter(pos=request.user)

    # 排序整合，用于前端呈现
    shown_instances = charge_org.union(applied_org).order_by("-modify_time", "-time")

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="新组织申请")
    return render(request, "neworganization_show.html", locals())


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
            if user_type == "Person" and application.person != me:
                html_display=user_login_org(request,application.org)
                if html_display['warn_code']==1:
                    return redirect(
                        "/welcome/"
                        + "?warn_code={}&warn_message={}".format(
                            html_display["warn_code"], html_display["warn_message"]
                        )
                    )
                else:
                    #防止后边有使用，因此需要赋值
                    user_type="Organization"
                    request.user=application.org.organization_id
                    me = application.org
            assert (application.org == me) or (application.person == me)

        except: #恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_code"] = "您没有权限访问该网址！"
            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        is_new_application = False # 前端使用量, 表示是老申请还是新的
        applied_org = application.org

    else:   # 如果不存在id, 默认应该传入org_name参数
        org_name = request.GET.get("org_name", None)
        try:
            applied_org = Organization.objects.activated().get(oname=org_name)
            assert user_type == "Person" # 只有个人能看到这个新建申请的界面

        except:
            # 非法的名字, 出现恶意修改参数的情况
            html_display["warn_code"] = 1
            html_display["warn_code"] = "网址遭到篡改，请检查网址的合法性或尝试重新进入人事申请页面"
            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        
        # 查找已经存在的审核中的申请
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
    app_avatar_path = apply_person.get_user_ava()
    org_avatar_path = applied_org.get_user_ava()
    # 获取个人与组织[在当前学年]的关系
    current_pos_list = Position.objects.current().filter(person=apply_person, org=applied_org)
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
    if not is_new_application:
        apply_type_list[application.apply_type]['selected'] = True
        if application.pos is not None:
            position_name_list[application.pos]['selected'] = True
        #未通过时，不能修改，但是需要呈现变量。
        if application.status != ModifyPosition.Status.PENDING:  # 未通过
            apply_type_list[application.apply_type]['disabled'] = False
            position_name_list[application.pos]["disabled"] = False

    

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
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="人事申请")
    return render(request, 'showPosition.html', locals())

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
    bar_display = utils.get_sidebar_and_navbar(request.user, "报销信息")
    return render(request, "reimbursement_show.html", locals())

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def showActivity(request):
    """
    活动信息的聚合界面
    只有老师和组织才能看到，老师看到检查者是自己的，组织看到发起方是自己的
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身
    is_teacher = False #该变量同时用于前端
    if user_type == "Person":
        try:
            person = utils.get_person_or_org(request.user, user_type)
            if person.identity == NaturalPerson.Identity.TEACHER :
                is_teacher = True
        except:
            pass
        if not is_teacher:
            html_display["warn_code"] = 1

            html_display["warn_code"] = "学生账号不能进入活动管理页面！"

            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
    if is_teacher:
        shown_instances = Activity.objects.all_activated().filter(examine_teacher = me.id)
    else:
        shown_instances = Activity.objects.all_activated().filter(organization_id = me.id)

    shown_instances = shown_instances.order_by("-modify_time", "-time")
    bar_display = utils.get_sidebar_and_navbar(request.user, "活动管理")
    return render(request, "activity_show.html", locals())


# 对一个已经完成的申请, 构建相关的通知和对应的微信消息, 将有关的事务设为已完成
# 如果有错误，则不应该是用户的问题，需要发送到管理员处解决
def make_relevant_notification(application, info):
    # 考虑不同post_type的信息发送行为
    post_type = info.get("post_type")
    feasible_post = ["new_submit", "modify_submit", "cancel_submit", "accept_submit", "refuse_submit"]

    # 统一该函数：判断application的类型
    application_type = type(application)
    # 准备呈现使用的变量与信息

    # 先准备一些复杂变量(只是为了写起来方便所以先定义，不然一大个插在后面的操作里很丑)
    if application_type == ModifyPosition:
        try:
            position_name = application.org.otype.get_name(application.pos)  # 职位名称
        except:
            position_name = "退出组织"
    elif application_type == ModifyOrganization:
        apply_person = NaturalPerson.objects.get(person_id=application.pos)
        inchage_person = application.otype.incharge
        try:
            new_org = Organization.objects.get(oname=application.oname)
        except:
            new_org = None

    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    if application_type == ModifyPosition:
        if post_type == 'new_submit':
            content = f'{application.person.name}发起组织人事变动申请，职位申请：{position_name}，请审核~'
        elif post_type == 'modify_submit':
            content = f'{application.person.name}修改了人事申请信息，请审核~'
        elif post_type == 'cancel_submit':
            content = f'{application.person.name}取消了人事申请信息。'
        elif post_type == 'accept_submit':
            content = f'恭喜，您申请的人事变动：{application.org.oname}，审核已通过！申请职位：{position_name}。'
        elif post_type == 'refuse_submit':
            content = f'抱歉，您申请的人事变动：{application.org.oname}，审核未通过！申请职位：{position_name}。'
        else:
            raise NotImplementedError
        applyer_id = application.person.person_id
        applyee_id = application.org.organization_id
        not_type = Notification.Title.POSITION_INFORM
        URL = f'/modifyPosition/?pos_id={application.id}'
    elif application_type == ModifyOrganization:
        if post_type == 'new_submit':
            content = f'{apply_person.name}发起新建组织申请，新建组织：{application.oname}，请审核~'
        elif post_type == 'modify_submit':
            content = f'{apply_person.name}修改了组织申请信息，请审核~'
        elif post_type == 'cancel_submit':
            content = f'{apply_person.name}取消了组织{application.oname}的申请。'
        elif post_type == 'accept_submit':
            content = f'恭喜，您申请的组织：{application.oname}，审核已通过！组织编号为{new_org.organization_id.username}, \
                初始密码为{utils.random_code_init(new_org.organization_id.id)}，请尽快登录修改密码。登录方式：(1)在负责人账户点击左侧「切换账号」；(2)从登录页面用组织编号或组织名称以及密码登录。'
        elif post_type == 'refuse_submit':
            content = f'抱歉，您申请的组织：{application.oname}，审核未通过！。'
        else:
            raise NotImplementedError
        applyer_id = apply_person.person_id
        applyee_id = inchage_person.person_id
        not_type = Notification.Title.NEW_ORGANIZATION
        URL = f'/modifyOrganization/?org_id={application.id}'

    sender = applyer_id if feasible_post.index(post_type) < 3 else applyee_id
    receiver = applyee_id if feasible_post.index(post_type) < 3 else applyer_id
    typename = Notification.Type.NEEDDO if post_type == 'new_submit' else Notification.Type.NEEDREAD
    title = Notification.Title.VERIFY_INFORM if post_type != 'accept_submit' else not_type
    relate_instance = application if post_type == 'new_submit' else None
    publish_to_wechat = True
    # TODO cancel是否要发送notification？是否发送微信？

    # 正式创建notification
    notification_create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
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


# 新建+修改+取消+审核 报销信息
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
def modifyReimbursement(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身

    # 前端使用量user_type，表示观察者是组织还是个人

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None
    # 根据是否有newid来判断是否是第一次
    reimb_id = request.GET.get("reimb_id", None)
    #审核老师
    auditor = User.objects.get(username=local_dict["audit_teacher"]["Funds"])
    auditor_name=utils.get_person_or_org(auditor).name

    if reimb_id is not None:  # 如果存在对应报销
        try:  # 尝试获取已经新建的Reimbursement
            application = Reimbursement.objects.get(id=reimb_id)
            if user_type == "Person" and auditor!=request.user:
                html_display=user_login_org(request,application.pos.organization)
                if html_display['warn_code']==1:
                    return redirect(
                        "/welcome/"
                        + "?warn_code={}&warn_message={}".format(
                            html_display["warn_code"], html_display["warn_message"]
                        )
                    )
                else:#成功
                    user_type="Organization"
                    request.user=application.pos
                    me = application.pos.organization

            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者被审核老师之一
            assert (application.pos==request.user) or (auditor==request.user)
        except:  # 恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_code"] = "您没有权限访问该网址！"
            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        is_new_application = False  # 前端使用量, 表示是老申请还是新的

    else:  # 如果不存在id, 默认应该传入活动信息
        #只有组织才有可能报销
        try:
            assert user_type == "Organization"
        except:  # 恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_code"] = "您没有权限访问该网址！"
            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        is_new_application = True  # 新的申请

         # 这种写法是为了方便随时取消某个条件
    #通知的接收者
    if user_type == "Organization":
        receiver= auditor
    else:
        receiver=application.pos
    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在组织新建申请的时候才可能出现，对应位is_new_application为True
        接下来POST
    '''

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST":
        # 如果是状态变更
        if request.POST.get("post_type", None) is not None:

            # 主要操作函数，更新申请状态
            context = update_reimb_application(application, me, user_type, request,auditor_name)

            if context["warn_code"] == 2:  # 成功修改申请
                # 回传id 防止意外的锁操作
                application = Reimbursement.objects.get(id=context["application_id"])
                is_new_application = False  # 状态变更

                # 处理通知相关的操作，并根据情况发送微信
                # 默认需要成功,失败也不是用户的问题，直接给管理员报错
                #组织名字
                org_name = application.pos.organization.oname
                #活动标题
                act_title = application.related_activity.title
                # 准备创建notification需要的构件：发送内容
                content = {
                    'new_submit': f'{org_name}发起活动{act_title}的经费申请，请审核~',
                    'modify_submit': f'{org_name}修改了活动{act_title}的经费申请，请审核~',
                    'cancel_submit': f'{org_name}取消了活动{act_title}的经费申请。',
                    'accept_submit': f'恭喜，您申请的经费申请：{act_title}，审核已通过！已扣除元气值{application.amount}',
                    'refuse_submit': f'抱歉，您申请的经费申请：{act_title}，审核未通过！',
                }
                #创建通知
                make_notification(application,request,content,receiver)
                if request.POST.get("post_type", None)=="new_submit":
                    is_new_application=True
                    application=None
            elif context["warn_code"] != 1:  # 没有返回操作提示
                raise NotImplementedError("处理经费申请中出现未预见状态，请联系管理员处理！")


        else:  # 如果是新增评论
            # 权限检查
            allow_comment = True if (not is_new_application) and (
                application.is_pending()) else False
            if not allow_comment:  # 存在不合法的操作
                return redirect(
                    "/welcome/?warn_code=1&warn_message=存在不合法操作,请与管理员联系!")
            context = addComment(request, application,receiver)

        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————
    '''
        组织：可能是新建、修改申请
        老师：可能是审核申请
    '''

    # (1) 是否允许修改表单
    # 组织写表格?
    allow_form_edit = True if (user_type == "Organization") and (
            is_new_application or application.is_pending()) else False
    # 老师审核?
    allow_audit_submit = True if (user_type == "Person") and (not is_new_application) and (
        application.is_pending()) else False

    # 是否可以评论
    commentable = True if (not is_new_application) and (application.is_pending()) \
        else False
    comments = showComment(application) if application is not None else None
    # 用于前端展示：如果是新申请，申请人即“me”，否则从application获取。
    apply_person = me if is_new_application else utils.get_person_or_org(application.pos)
    #申请人头像
    app_avatar_path = apply_person.get_user_ava()

    # 未报销活动
    activities = utils.get_unreimb_activity(apply_person)
    #元培学院
    our_college=Organization.objects.get(oname="元培学院") if allow_audit_submit else None

    # TODO: 设置默认值

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="经费申请详情")
    return render(request, "modify_reimbursement.html", locals())


# 对一个已经完成的申请, 构建相关的通知和对应的微信消息, 将有关的事务设为已完成
# 如果有错误，则不应该是用户的问题，需要发送到管理员处解决
#用于报销的通知
def make_notification(application, request,content,receiver):
    # 考虑不同post_type的信息发送行为
    post_type = request.POST.get("post_type")
    feasible_post = ["new_submit", "modify_submit", "cancel_submit", "accept_submit", "refuse_submit"]


    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    URL = {
        'modifyposition': f'/modifyPosition/?pos_id={application.id}',
        'neworganization': f'/modifyOrganization/?org_id={application.id}',
        'reimbursement': f'/modifyReimbursement/?reimb_id={application.id}',
    }
    sender = request.user
    typename = Notification.Type.NEEDDO if post_type == 'new_submit' else Notification.Type.NEEDREAD
    title = Notification.Title.VERIFY_INFORM if post_type != 'accept_submit' else Notification.Title.POSITION_INFORM

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
        URL=URL[application.typename],
        relate_instance=relate_instance,
        publish_to_wechat=publish_to_wechat
    )
    # 对于处理类通知的完成(done)，修改状态
    # 这里的逻辑保证：所有的处理类通知的生命周期必须从“人事发起”开始，从“取消”“通过”“拒绝”结束。
    if feasible_post.index(post_type) >= 2:
        notification_status_change(
            application.relate_notifications.get(status=Notification.Status.UNDONE).id,
            Notification.Status.DONE
        )

# YWolfeee: 重构组织申请页面 Aug 24 12:30 UTC-8
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def modifyOrganization(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身
    if user_type == "Organization":
        html_display["warn_code"] = 1
        html_display["warn_code"] = "请不要使用组织账号申请新组织！"
        return redirect(
            "/welcome/"
            + "?warn_code={}&warn_message={}".format(
                html_display["warn_code"], html_display["warn_message"]
            )
        )

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None

    # 根据是否有newid来判断是否是第一次
    org_id = request.GET.get("org_id", None)

    if org_id is not None: # 如果存在对应申请
        try:    # 尝试获取已经新建的Position
            application = ModifyOrganization.objects.get(id = org_id)
            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者审核老师
            assert (application.pos == request.user) or (application.otype.incharge == me)
        except: #恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_code"] = "您没有权限访问该网址！"
            return redirect(
                "/welcome/"
                + "?warn_code={}&warn_message={}".format(
                    html_display["warn_code"], html_display["warn_message"]
                )
            )
        is_new_application = False # 前端使用量, 表示是老申请还是新的

    else:   
        # 如果不存在id, 是一个新建组织页面。
        # 已保证组织不可能访问，任何人都可以发起新建组织。
        application = None
        is_new_application = True
        
    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在个人新建申请的时候才可能出现，对应位is_new_application
        接下来POST
    '''

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST":
        # 如果是状态变更
        if request.POST.get("post_type", None) is not None:            

            # 主要操作函数，更新申请状态 TODO
            context = update_org_application(application, me, request)

            if context["warn_code"] == 2:   # 成功修改申请
                # 回传id 防止意外的锁操作
                application = ModifyOrganization.objects.get(id = context["application_id"])
                is_new_application = False #状态变更
                if request.POST.get("post_type") == "new_submit":   
                    # 重要！因为该界面没有org_id，重新渲染新建界面
                    is_new_application = True

                # 处理通知相关的操作，并根据情况发送微信
                # 默认需要成功,失败也不是用户的问题，直接给管理员报错 TODO
                try:
                    make_relevant_notification(application, request.POST)    
                except:
                    raise NotImplementedError

            elif context["warn_code"] != 1: # 没有返回操作提示
                raise NotImplementedError("处理组织申请中出现未预见状态，请联系管理员处理！")   
            

        else:   # 如果是新增评论
            # 权限检查
            allow_comment = True if (not is_new_application) and (
                application.is_pending()) else False
            if not allow_comment:   # 存在不合法的操作
                return redirect(
                    "/welcome/?warn_code=1&warn_message=存在不合法操作,请与管理员联系!")
            context = addComment(request, application, \
                application.otype.incharge.person_id if me.person_id == application.pos \
                    else application.pos)

        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    org_type_list = {
        w:{
            'display' : str(w),  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for w in OrganizationType.objects.all()
    }

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
    allow_form_edit = True if (
                is_new_application or (application.pos == me.person_id and application.is_pending())) else False
    # 组织审核?
    allow_audit_submit = True if (not is_new_application) and (
                application.is_pending()) and (application.otype.incharge == me) else False
    # 评论区?
    allow_comment = True if (not is_new_application) and (application.is_pending()) \
                    else False

    # (2) 表单变量的默认值

        # 首先禁用一些选项
    
    # 评论区
    commentable = allow_comment
    # comments = showComment(application) if application is not None else None
    comments = showComment(application)
    # 用于前端展示
    apply_person = me if is_new_application else NaturalPerson.objects.get(person_id=application.pos)
    app_avatar_path = apply_person.get_user_ava()
    org_avatar_path = utils.get_user_ava(application, "Organization")
    org_types = OrganizationType.objects.order_by("-otype_id").all()  # 当前组织类型，前端展示需要
    former_img = Organization().get_user_ava()
    if not is_new_application:
        org_type_list[application.otype]['selected'] = True

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="组织申请详情")
    return render(request, "modify_organization.html", locals())

# YWolfeee: 重构人事申请页面 Aug 24 12:30 UTC-8
@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
def sendMessage(request):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身
    if user_type == "Person":
        html_display["warn_code"] = 1
        html_display["warn_code"] = "只有组织账号才能发送通知！"
        return redirect(
            "/welcome/"
            + "?warn_code={}&warn_message={}".format(
                html_display["warn_code"], html_display["warn_message"]
            )
        )
    
    if request.method == "POST":
        # 合法性检查
        context = send_message_check(me,request)
        
        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]


    # 前端展示量
    receiver_type_list = {
        w:{
            'display' : w,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for w in ['订阅用户','组织成员']
    }

    # 设置默认量
    if request.POST.get('receiver_type', None) is not None:
        receiver_type_list[request.POST.get('receiver_type')]['selected'] = True
    if request.POST.get('url', None) is not None:
        url = request.POST.get('url', None)
    if request.POST.get('content', None) is not None:
        content = request.POST.get('content', None)
    if request.POST.get('title', None) is not None:
        title = request.POST.get('title', None)



    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="信息发送中心")
    return render(request, "sendMessage.html", locals())

                
def send_message_check(me, request):
    # 已经检查了我的类型合法，并且确认是post
    # 设置默认量
    receiver_type = request.POST.get('receiver_type', None)
    url = request.POST.get('url', "")
    content = request.POST.get('content', "")
    title = request.POST.get('title', "")

    if receiver_type is None:
        return wrong("发生了意想不到的错误：未接收到您选择的发送者类型！请联系管理员~")
    
    if len(content) == 0:
        return wrong("请填写通知的内容！")
    elif len(content) > 225:
        return wrong("通知的长度不能超过225个字！你超过了！")
    
    if len(title) == 0:
        return wrong("不能不写通知的标题！补起来！")
    elif len(title) > 10:
        return wrong("通知的标题不能超过10个字！不然发出来的通知会很丑！")
    
    if len(url) == 0:
        url = None

    not_list = []
    sender = me.organization_id
    status = Notification.Status.UNDONE
    title = title
    content = content
    typename = Notification.Type.NEEDREAD
    URL = url
    try:
        if receiver_type == "订阅用户":
            receivers = NaturalPerson.objects.exclude(id__in=me.unsubscribers.all())
            receivers = [receiver.person_id for receiver in receivers]
        else:   # 检查过逻辑了，不可能是其他的
            receivers = NaturalPerson.objects.filter(
                id__in=me.position_set.values_list('person_id', flat=True))
            receivers = [receiver.person_id for receiver in receivers]
        # 创建通知
        success, bulk_identifier = bulk_notification_create(
                receivers=receivers,
                sender=sender,
                typename=typename,
                title=title,
                content=content,
                URL=URL,
            )
        assert success
    except:
        return wrong("创建通知的时候出现错误！请联系管理员！")
    try:
        assert publish_notifications(filter_kws={'bulk_identifier': bulk_identifier})
    except:
        return wrong("发送微信的过程出现错误！请联系管理员！")
    
    return succeed(f"成功将创建知晓类消息，发送给所有的{receiver_type}了!")
        
