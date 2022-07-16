from app.views_dependency import *
from app.models import (
    Feedback,
    NaturalPerson,
    Freshman,
    Position,
    Organization,
    OrganizationTag,
    OrganizationType,
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
    QandA,
    ReimbursementPhoto,
    Course,
    CourseRecord,
    Semester,
    PageLog,
    ModuleLog,
)
from app.utils import (
    url_check,
    check_cross_site,
    get_person_or_org,
    record_modify_with_session,
    update_related_account_in_session,
)
from app.wechat_send import(
    publish_notification,
    publish_notifications,
    send_wechat_captcha,
    invite,
    WechatApp,
    WechatMessageLevel,
)
from app.notification_utils import(
    notification_create,
    bulk_notification_create,
    notification_status_change,
    notification2Display,
)
from app.QA_utils import (
    QA2Display,
    QA_anwser,
    QA_create,
    QA_delete,
    QA_ignore,
)
import json
import random
import requests  # 发送验证码
from datetime import date, datetime, timedelta

from boottest import local_dict
from django.contrib import auth, messages
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction
from django.db.models import Q, F, Sum
from django.contrib.auth.password_validation import CommonPasswordValidator, NumericPasswordValidator
from django.core.exceptions import ValidationError


email_url = local_dict["url"]["email_url"]
hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])
email_coder = MySHA256Hasher(local_dict["hash"]["email"])


@log.except_captured(source='views[index]', record_user=True,
                     record_request_args=True, show_traceback=True)
def index(request: HttpRequest):
    arg_origin = request.GET.get("origin")
    modpw_status = request.GET.get("modinfo")
    arg_islogout = request.GET.get("is_logout")
    alert = request.GET.get("alert")
    if request.session.get('alert_message'):
        load_alert_message = request.session.pop('alert_message')
    html_display = dict()
    if (
            request.method == "GET"
            and modpw_status is not None
            and modpw_status == "success"
    ):
        succeed("修改密码成功!", html_display)
        auth.logout(request)
        return render(request, "index.html", locals())

    if alert is not None:
        wrong("检测到异常行为，请联系系统管理员。", html_display)
        auth.logout(request)
        return render(request, "index.html", locals())

    if arg_islogout is not None:
        if request.user.is_authenticated:
            auth.logout(request)
            return render(request, "index.html", locals())
    if arg_origin is None:  # 非外部接入
        if request.user.is_authenticated:
            return redirect("/welcome/")

    # 非法的 origin
    if not url_check(arg_origin):
        request.session['alert_message'] = f"尝试跳转到非法 URL: {arg_origin}，跳转已取消。"
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
            wrong(local_dict["msg"]["404"], html_display)
            return render(request, "index.html", locals())
        userinfo = auth.authenticate(username=username, password=password)
        if userinfo:
            auth.login(request, userinfo)
            valid, user_type, html_display = utils.check_user_type(request.user)
            if not valid:
                return redirect("/logout/")
            if user_type == UTYPE_PER:
                me = get_person_or_org(userinfo, user_type)
                if me.first_time_login:
                    # 不管有没有跳转，这个逻辑都应该是优先的
                    # TODO：应该在修改密码之后做一个跳转
                    return redirect("/modpw/")
                update_related_account_in_session(request, username)
            if arg_origin is None:
                return redirect("/welcome/")
        else:
            wrong(local_dict["msg"]["406"], html_display)

    # 所有跳转，现在不管是不是post了
    if arg_origin is not None and request.user.is_authenticated:
        if not check_cross_site(request, arg_origin):
            return redirect(message_url(wrong('目标域名非法，请警惕陌生链接。')))
        return redirect(arg_origin)

    return render(request, "index.html", locals())


@login_required(redirect_field_name="origin")
@log.except_captured(source='views[shiftAccount]', record_user=True)
def shiftAccount(request: HttpRequest):

    username = request.session.get("NP")
    if not username:
        return redirect(message_url(wrong('没有可切换的账户信息，请重新登录!')))

    oname = ""
    if request.method == "GET" and request.GET.get("oname"):
        oname = request.GET["oname"]

    # 不一定更新成功，但无所谓
    update_related_account_in_session(request, username, shift=True, oname=oname)

    if request.method == "GET" and request.GET.get("origin"):
        arg_url = request.GET["origin"]
        if url_check(arg_url) and check_cross_site(request, arg_url) :
            if not arg_url.startswith('http'): # 暂时只允许内部链接
                return redirect(arg_url)
    return redirect("/welcome/")




# Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5PasswordHasher("wechat_login")


@log.except_captured(source='views[miniLogin]', record_user=True)
def miniLogin(request: HttpRequest):
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

            # request.session["username"] = username 已废弃
            en_pw = hash_coder.encode(username)
            user_account = NaturalPerson.objects.get(person_id=username)
            return JsonResponse({"Sname": user_account.name, "Succeed": 1}, status=200)
        else:
            return JsonResponse({"Sname": username, "Succeed": 0}, status=400)
    except:
        return JsonResponse({"Sname": "", "Succeed": 0}, status=400)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[stuinfo]', record_user=True)
def stuinfo(request: HttpRequest, name=None):
    """
        进入到这里的逻辑:
        首先必须登录，并且不是超级账户
        如果name是空
            如果是个人账户，那么就自动跳转个人主页"/stuinfo/?name=myname"
            如果是小组账户，那么自动跳转welcome
        如果name非空但是找不到对应的对象
            自动跳转到welcome
        如果name有明确的对象
            如果不重名
                如果是自己，那么呈现并且有左边栏
                如果不是自己或者自己是小组，那么呈现并且没有侧边栏
            如果重名
                那么期望有一个"+"在name中，如果搜不到就跳转到Search/?Query=name让他跳转去
    """

    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)

    oneself = get_person_or_org(user, user_type)

    if name is None:
        name = request.GET.get('name', None)
    if name is None:
        if user_type == "Organization":
            return redirect("/orginfo/")  # 小组只能指定学生姓名访问
        else:  # 跳轉到自己的頁面
            assert user_type == "Person"
            return redirect(append_query(oneself.get_absolute_url(), **request.GET.dict()))
    else:
        # 先对可能的加号做处理
        name_list = name.replace(' ', '+').split("+")
        name = name_list[0]
        person = NaturalPerson.objects.activated().filter(name=name)
        if len(person) == 0:  # 查无此人
            return redirect(message_url(wrong('用户不存在!')))
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
        inform_share, alert_message = utils.get_inform_share(me=person, is_myself=is_myself)

        # 处理更改数据库中inform_share的post
        if request.POST.get("question") is not None:
            anonymous_flag = (request.POST.get('show_name') is not None)
            question = request.POST.get("question")
            if len(question) == 0:
                wrong("请填写问题内容!", html_display)
            else:
                try:
                    QA_create(sender=request.user,receiver=person.person_id,Q_text=str(question),anonymous_flag=anonymous_flag)
                    succeed("提问发送成功!", html_display)
                except:
                    wrong("提问发送失败!请联系管理员!", html_display)
            return redirect(message_url(html_display, person.get_absolute_url()))
        elif request.method == "POST" and request.POST:
            option = request.POST.get("option", "")
            assert option == "cancelInformShare" and html_display["is_myself"]
            person.inform_share = False
            person.save()
            return redirect("/welcome/")



        # ----------------------------------- 小组卡片 ----------------------------------- #

        person_poss = Position.objects.activated().filter(Q(person=person))
        person_orgs = Organization.objects.filter(
            id__in=person_poss.values("org")
        )  # ta属于的小组
        oneself_orgs = (
            [oneself]
            if user_type == "Organization"
            else Position.objects.activated().filter(
                Q(person=oneself) & Q(show_post=True)
            )
        )
        oneself_orgs_id = [oneself.id] if user_type == "Organization" else oneself_orgs.values("org") # 自己的小组

        # 管理的小组
        person_owned_poss = person_poss.filter(is_admin=True, status=Position.Status.INSERVICE)
        person_owned_orgs = person_orgs.filter(
            id__in=person_owned_poss.values("org")
        )  # ta管理的小组
        person_owned_orgs_ava = [
            # utils.get_user_ava(org, "organization") for org in person_owned_orgs
            org.get_user_ava() for org in person_owned_orgs
        ]
        person_owned_orgs_pos = [
            person_owned_poss.get(org=org).pos for org in person_owned_orgs
        ]  # ta在小组中的职位
        person_owned_orgs_pos = [
            org.otype.get_name(pos)
            for pos, org in zip(person_owned_orgs_pos, person_owned_orgs)
        ]  # ta在小组中的职位
        html_display["owned_orgs_info"] = (
                list(zip(person_owned_orgs, person_owned_orgs_ava, person_owned_orgs_pos))
                or None
        )

        # 属于的小组
        person_joined_poss = person_poss.filter(~Q(is_admin=True) & Q(show_post=True))
        person_joined_orgs = person_orgs.filter(
            id__in=person_joined_poss.values("org")
        )  # ta属于的小组
        person_joined_orgs_ava = [
            org.get_user_ava() for org in person_joined_orgs
        ]
        person_joined_orgs_pos = [
            person_joined_poss.get(org=org).pos for org in person_joined_orgs
        ]  # ta在小组中的职位
        person_joined_orgs_pos = [
            org.otype.get_name(pos)
            for pos, org in zip(person_joined_orgs_pos, person_joined_orgs)
        ]  # ta在小组中的职位
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

        # 历史的小组(同样是删去隐藏)
        person_history_poss = Position.objects.activated(noncurrent=True).filter(
            person=person,
            show_post=True
            )
        person_history_orgs = Organization.objects.filter(
            id__in=person_history_poss.values("org")
        )  # ta属于的小组
        person_history_orgs_ava = [
            # utils.get_user_ava(org, "organization") for org in person_owned_orgs
            org.get_user_ava() for org in person_history_orgs
        ]
        person_history_orgs_pos = [
            person_history_poss.get(org=org).pos for org in person_history_orgs
        ]  # ta在小组中的职位

        sems = {
            Semester.FALL: "秋",
            Semester.SPRING: "春",
            Semester.ANNUAL: "全年"
        }

        person_history_orgs_pos = [
            org.otype.get_name(pos) + ' ' +
            str(person_history_poss.get(org=org).in_year)[2:] + "-" +
            str(person_history_poss.get(org=org).in_year + 1)[2:] +
            sems[person_history_poss.get(org=org).in_semester]
            for pos, org in zip(person_history_orgs_pos, person_history_orgs)
        ]  # ta在小组中的职位
        html_display["history_orgs_info"] = (
                list(zip(person_history_orgs, person_history_orgs_ava, person_history_orgs_pos))
                or None
        )

        # 隐藏的小组(所有学期都会呈现，不用activated)
        person_hidden_poss = Position.objects.filter(person=person, show_post = False)
        person_hidden_orgs = Organization.objects.filter(
            id__in=person_hidden_poss.values("org")
        )  # ta属于的小组
        person_hidden_orgs_ava = [
            # utils.get_user_ava(org, "organization") for org in person_hidden_orgs
            org.get_user_ava() for org in person_hidden_orgs
        ]
        person_hidden_orgs_pos = [
            person_hidden_poss.get(org=org).pos for org in person_hidden_orgs
        ]  # ta在小组中的职位
        person_hidden_orgs_pos = [
            org.otype.get_name(pos)
            for pos, org in zip(person_hidden_orgs_pos,person_hidden_orgs)
        ]  # ta在小组中的职位
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

        # ------------------ 学时查询 ------------------ #

        # 只有是自己的主页时才显示学时
        if is_myself:
            # 把当前学期的活动去除
            course_me_past = CourseRecord.objects.past().filter(person_id=oneself)

            # 无效学时，在前端呈现
            course_no_use = (
                course_me_past
                .filter(invalid=True)
            )

            # 特判，需要一定时长才能计入总学时
            course_me_past = (
                course_me_past
                .exclude(invalid=True)
            )

            course_me_past = course_me_past.order_by('year', 'semester')
            course_no_use = course_no_use.order_by('year', 'semester')

            progress_list = []

            # 计算每个类别的学时
            for course_type in list(Course.CourseType): # CourseType.values亦可
                progress_list.append((
                    course_me_past
                    .filter(course__type=course_type)
                    .aggregate(Sum('total_hours'))
                )['total_hours__sum'] or 0)

            # 计算没有对应Course的学时
            progress_list.append((
                course_me_past
                .filter(course__isnull=True)
                .aggregate(Sum('total_hours'))
            )['total_hours__sum'] or 0)

            # 每个人的规定学时，按年级讨论
            try:
                # 本科生
                if int(oneself.stu_grade) <= 2018:
                    ruled_hours = 0
                elif int(oneself.stu_grade) == 2019:
                    ruled_hours = 32
                else:
                    ruled_hours = 64
            except:
                # 其它，如老师和住宿辅导员等
                ruled_hours = 0

            # 计算总学时
            total_hours_sum = sum(progress_list)
            # 用于算百分比的实际总学时（考虑到可能会超学时），仅后端使用
            actual_total_hours = max(total_hours_sum, ruled_hours)
            if actual_total_hours > 0:
                progress_list = [
                    hour / actual_total_hours * 100 for hour in progress_list
                ]


        # ------------------ 活动参与 ------------------ #

        participants = Participant.objects.activated().filter(person_id=person)
        activities = Activity.objects.activated().filter(
            Q(id__in=participants.values("activity_id")),
            # ~Q(status=Activity.Status.CANCELED), # 暂时可以呈现已取消的活动
        )
        if user_type == "Person":
            # 因为上面筛选过活动，这里就不用筛选了
            # 之前那个写法是O(nm)的
            activities_me = Participant.objects.activated().filter(person_id=oneself)
            activities_me = set(activities_me.values_list("activity_id_id", flat=True))
        else:
            activities_me = activities.filter(organization_id=oneself)
            activities_me = set(activities_me.values_list("id", flat=True))
        activity_is_same = [
            activity in activities_me
            for activity in activities.values_list("id", flat=True)
        ]
        activity_info = list(zip(activities, activity_is_same))
        activity_info.sort(key=lambda a: a[0].start, reverse=True)
        html_display["activity_info"] = list(activity_info) or None

        # 呈现历史活动，不考虑共同活动的规则，直接全部呈现
        history_activities = list(
            Activity.objects.activated(noncurrent=True).filter(
            Q(id__in=participants.values("activity_id")),
            # ~Q(status=Activity.Status.CANCELED), # 暂时可以呈现已取消的活动
        ))
        history_activities.sort(key=lambda a: a.start, reverse=True)
        html_display["history_act_info"] = list(history_activities) or None

        # 警告呈现信息

        try:
            html_display["warn_code"] = int(
                request.GET.get("warn_code", 0)
            )  # 是否有来自外部的消息
        except:
            return redirect(message_url(wrong('非法的状态码，请勿篡改URL!')))
        html_display["warn_message"] = request.GET.get("warn_message", "")  # 提醒的具体内容

        modpw_status = request.GET.get("modinfo", None)
        if modpw_status is not None and modpw_status == "success":
            html_display["warn_code"] = 2
            html_display["warn_message"] = "修改个人信息成功!"

        # 存储被查询人的信息
        context = dict()

        context["person"] = person

        context["title"] = "我" if is_myself else (
            {0: "他", 1: "她"}.get(person.gender, 'Ta') if person.show_gender else "Ta")

        context["avatar_path"] = person.get_user_ava()
        context["wallpaper_path"] = utils.get_user_wallpaper(person, "Person")

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display
        bar_display = utils.get_sidebar_and_navbar(
            request.user, navbar_name="个人主页", title_name = person.name
            )
        origin = request.get_full_path()

        if request.session.get('alert_message'):
            load_alert_message = request.session.pop('alert_message')

        # 浏览次数，必须在render之前
        # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
        NaturalPerson.objects.filter(id=person.id).update(visit_times=F('visit_times')+1)
        # person.visit_times += 1
        # person.save()
        return render(request, "stuinfo.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[requestLoginOrg]', record_user=True)
def requestLoginOrg(request: HttpRequest, name=None):  # 特指个人希望通过个人账户登入小组账户的逻辑
    """
        这个函数的逻辑是，个人账户点击左侧的管理小组直接跳转登录到小组账户
        首先检查登录的user是个人账户，否则直接跳转orginfo
        如果个人账户对应的是name对应的小组的最高权限人，那么允许登录，否则跳转回stuinfo并warning
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)

    if user_type == "Organization":
        return redirect("/orginfo/")
    try:
        me = NaturalPerson.objects.activated().get(person_id=user)
    except:  # 找不到合法的用户
        return redirect(message_url(wrong('用户不存在!')))
    if name is None:  # 个人登录未指定登入小组,属于不合法行为,弹回欢迎
        name = request.GET.get('name', None)
    if name is None:  # 个人登录未指定登入小组,属于不合法行为,弹回欢迎
        return redirect(message_url(wrong('无效的小组信息!')))
    else:  # 确认有无这个小组
        try:
            org = Organization.objects.get(oname=name)
        except:  # 找不到对应小组
            urls = "/stuinfo/?name=" + me.name + "&warn_code=1&warn_message=找不到对应小组,请联系管理员!"
            return redirect(urls)
        try:
            position = Position.objects.activated().filter(org=org, person=me)
            assert len(position) == 1
            position = position[0]
            assert position.is_admin == True
        except:
            urls = "/stuinfo/?name=" + me.name + "&warn_code=1&warn_message=没有登录到该小组账户的权限!"
            return redirect(urls)
        # 到这里,是本人小组并且有权限登录
        auth.logout(request)
        auth.login(request, org.organization_id)  # 切换到小组账号
        utils.update_related_account_in_session(request, user.username, oname=org.oname)
        if org.first_time_login:
            return redirect("/modpw/")
        return redirect("/orginfo/?warn_code=2&warn_message=成功切换到"+str(org)+"的账号!")





@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[orginfo]', record_user=True)
def orginfo(request: HttpRequest, name=None):
    """
        orginfo负责呈现小组主页，逻辑和stuinfo是一样的，可以参考
        只区分自然人和法人，不区分自然人里的负责人和非负责人。任何自然人看这个小组界面都是【不可管理/编辑小组信息】
    """
    user = request.user
    valid, user_type, html_display = utils.check_user_type(request.user)

    if not valid:
        return redirect("/logout/")

    me = get_person_or_org(user, user_type)

    if name is None:
        name = request.GET.get('name', None)

    if name is None:  # 此时登陆的必需是法人账号，如果是自然人，则跳转welcome
        if user_type == "Person":
            return redirect(message_url(wrong('个人账号不能登陆小组主页!')))
        try:
            org = Organization.objects.activated().get(organization_id=user)
        except:
            return redirect(message_url(wrong('用户小组不存在或已经失效!')))

        full_path = request.get_full_path()
        append_url = "" if ("?" not in full_path) else "&" + full_path.split("?")[1]

        return redirect("/orginfo/?name=" + org.oname + append_url)

    try:  # 指定名字访问小组账号的，可以是自然人也可以是法人。在html里要注意区分！

        # 下面是小组信息

        org = Organization.objects.activated().get(oname=name)
        org_tags = org.tags.all()

    except:
        return redirect(message_url(wrong('该小组不存在!')))

    # 判断是否为小组账户本身在登录
    html_display["is_myself"] = me == org
    inform_share, alert_message = utils.get_inform_share(me=me, is_myself=html_display["is_myself"])

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
        elif request.POST.get("option", "") == "cancelInformShare" and html_display["is_myself"]:
            org.inform_share = False
            org.save()
            return redirect("/welcome/")
        elif request.POST.get("question") is not None:
            anonymous_flag = (request.POST.get('show_name') is not None)
            question = request.POST.get("question")
            if len(question) == 0:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "请填写问题内容!"
            elif html_display['is_myself']:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "不能向自己提问!"
            else:
                try:
                    QA_create(sender=request.user,receiver=org.organization_id,Q_text=str(question),anonymous_flag=anonymous_flag)
                    html_display["warn_code"] = 2
                    html_display["warn_message"] = "提问发送成功!"
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "提问发送失败!请联系管理员!"
            return redirect(message_url(html_display, f"/orginfo/?name={organization_name}"))



    # 该学年、该学期、该小组的 活动的信息,分为 未结束continuing 和 已结束ended ，按时间顺序降序展现
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

    # 筛选历史活动，具体为不是这个学期的活动
    history_activity_list = (
        Activity.objects.activated(noncurrent=True)
        .filter(organization_id=org)
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

    # 处理历史活动
    history_activity_list_participantrec = []
    for act in history_activity_list:
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
        history_activity_list_participantrec.append(dictmp)


    # 判断我是不是老大, 首先设置为false, 然后如果有person_id和user一样, 就为True
    html_display["isboss"] = False

    # 小组成员list
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
        return redirect(message_url(wrong('非法的状态码，请勿篡改URL!')))
    html_display["warn_message"] = request.GET.get(
        "warn_message", "")  # 提醒的具体内容

    modpw_status = request.GET.get("modinfo", None)
    if modpw_status is not None and modpw_status == "success":
        html_display["warn_code"] = 2
        html_display["warn_message"] = "修改小组信息成功!"

    # 补充左边栏信息



    # 再处理修改信息的回弹
    modpw_status = request.GET.get("modinfo", None)
    html_display["modpw_code"] = modpw_status is not None and modpw_status == "success"


    # 小组活动的信息

    # 补充一些呈现信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user,navbar_name = "小组主页", title_name = org.oname)
    # 转账后跳转
    origin = request.get_full_path()

    # 补充订阅该小组的按钮
    allow_unsubscribe = org.otype.allow_unsubscribe # 是否允许取关
    is_person = True if user_type == "Person" else False
    if is_person:
        subscribe_flag = True if (
            organization_name not in me.unsubscribe_list.values_list("oname", flat=True)) \
            else False

    # 补充作为小组成员，选择是否展示的按钮
    show_post_change_button = False     # 前端展示“是否不展示我自己”的按钮，若为True则渲染这个按钮
    if user_type == 'Person':
        my_position = Position.objects.activated().filter(org=org, person=me).exclude(is_admin=True)
        if len(my_position):
            show_post_change_button = True
            my_position = my_position[0]


    if request.session.get('alert_message'):
        load_alert_message = request.session.pop('alert_message')

    # 浏览次数，必须在render之前
    # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
    Organization.objects.filter(id=org.id).update(visit_times=F('visit_times')+1)
    # org.visit_times += 1
    # org.save()
    return render(request, "orginfo.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[homepage]', record_user=True)
def homepage(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_person = True if user_type == "Person" else False
    me = get_person_or_org(request.user, user_type)

    html_display["is_myself"] = True

    try:
        html_display["warn_code"] = int(
            request.GET.get("warn_code", 0))  # 是否有来自外部的消息
    except:
        return redirect(message_url(wrong('非法的状态码，请勿篡改URL!')))
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
                html_display['first_signin'] = True # 前端显示

    # 开始时间在前后一周内，除了取消和审核中的活动。按时间逆序排序
    recentactivity_list = Activity.objects.get_recent_activity().select_related('organization_id')

    # 开始时间在今天的活动,且不展示结束的活动。按开始时间由近到远排序
    activities = Activity.objects.get_today_activity().select_related('organization_id')
    activities_start = [
        activity.start.strftime("%H:%M") for activity in activities
    ]
    html_display['today_activities'] = list(zip(activities, activities_start)) or None

    # 最新一周内发布的活动，按发布的时间逆序
    newlyreleased_list = Activity.objects.get_newlyreleased_activity().select_related('organization_id')

    # 即将截止的活动，按截止时间正序
    prepare_times = Activity.EndBeforeHours.prepare_times
    signup_rec = Activity.objects.activated().select_related(
        'organization_id').filter(status = Activity.Status.APPLYING)
    signup_list = []
    for act in signup_rec:
        deadline = act.apply_end
        dictmp = {}
        dictmp["deadline"] = deadline
        dictmp["act"] = act
        dictmp["tobestart"] = (deadline - nowtime).total_seconds()//360/10
        signup_list.append(dictmp)
    signup_list.sort(key=lambda x:x["deadline"])
    signup_list = signup_list[:10]
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
        time__gt = nowtime - timedelta(days = 7)
    )
    wishes = wishes[:100]

    # 心愿墙背景图片
    colors = Wishes.COLORS
    backgroundpics = [
            {
                "src": f"/static/assets/img/backgroundpics/{i+1}.png",
                "color": color
            } for i, color in enumerate(colors)
        ]

    # 从redirect.json读取要作为引导图的图片，按照原始顺序
    guidepicdir = "static/assets/img/guidepics"
    with open(f"{guidepicdir}/redirect.json") as file:
        img2url = json.load(file)
    guidepics = list(img2url.items())
    # (firstpic, firsturl), guidepics = guidepics[0], guidepics[1:]
    # firstpic是第一个导航图，不是第一张图片，现在把这个逻辑在模板处理了

    """ 
        取出过去一周的所有活动，filter出上传了照片的活动，从每个活动的照片中随机选择一张
        如果列表为空，那么添加一张default，否则什么都不加。
    """
    all_photo_display = ActivityPhoto.objects.filter(type=ActivityPhoto.PhotoType.SUMMARY).order_by('-time')
    photo_display, activity_id_set = list(), set()  # 实例的哈希值未定义，不可靠
    count = 9 - len(guidepics)  # 算第一张导航图
    for photo in all_photo_display:
        # 不用activity，因为外键需要访问数据库
        if photo.activity_id not in activity_id_set and photo.image:
            # 数据库设成了image可以为空而不是空字符串，str的判断对None没有意义

            photo.image = MEDIA_URL + str(photo.image)
            photo_display.append(photo)
            activity_id_set.add(photo.activity_id)
            count -= 1

            if count <= 0:  # 目前至少能显示一个，应该也合理吧
                break
    if photo_display:
        guidepics = guidepics[1:]   # 第一张只是封面图，如果有需要呈现的内容就不显示

    """ 暂时不需要这些，目前逻辑是取photo_display的前四个，如果没有也没问题
    if len(photo_display) == 0: # 这个分类是为了前端显示的便利，就不采用append了
        homepagephoto = "/static/assets/img/taskboard.jpg"
    else:
        firstpic = photo_display[0]
        photos = photo_display[1:]
    """

    # -----------------------------天气---------------------------------
    try:
        with open("./weather.json") as weather_json:
            html_display['weather'] = json.load(weather_json)
    except:
        from app.scheduler_func import get_weather
        html_display['weather'] = get_weather()
    update_time_delta = datetime.now() - datetime.strptime(html_display["weather"]["modify_time"],'%Y-%m-%d %H:%M:%S.%f')
    # 根据更新时间长短，展示不同的更新天气时间状态
    def days_hours_minutes_seconds(td):
        return td.days, td.seconds // 3600, (td.seconds // 60) % 60, td.seconds % 60
    days, hours, minutes, seconds = days_hours_minutes_seconds(update_time_delta)
    if days > 0:
        last_update = f"{days}天前"
    elif hours > 0:
        last_update = f"{hours}小时前"
    elif minutes > 0:
        last_update = f"{minutes}分钟前"
    else:
        last_update = f"{seconds}秒前"
    #-------------------------------天气结束-------------------------

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "元培生活")
    # bar_display["title_name"] = "Welcome Page"
    # bar_display["navbar_name"] = "元培生活"

    return render(request, "welcome_page.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[accountSetting]', record_user=True)
def accountSetting(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)

    # 在这个页面 默认回归为自己的左边栏
    html_display["is_myself"] = True
    user = request.user
    me = get_person_or_org(user, user_type)
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
            attr_check_list = [attr for attr in attr_dict.keys() if attr not in ['gender', 'ava', 'wallpaper', 'accept_promote', 'wechat_receive_level']]
            if html_display['warn_code'] == 1:
                return render(request, "person_account_setting.html", locals())

            modify_info = []
            if attr_dict['gender'] != useroj.get_gender_display():
                modify_info.append(f'gender: {useroj.get_gender_display()}->{attr_dict["gender"]}')
            if attr_dict['accept_promote'] != useroj.get_accept_promote_display():
                modify_info.append(f'accept_promote: {useroj.get_accept_promote_display()}->{attr_dict["accept_promote"]}')
            if attr_dict['wechat_receive_level'] != useroj.get_wechat_receive_level_display():
                modify_info.append(f'wechat_receive_level: {useroj.get_wechat_receive_level_display()}->{attr_dict["wechat_receive_level"]}')
            if attr_dict['ava']:
                modify_info.append(f'avatar: {attr_dict["ava"]}')
            if attr_dict['wallpaper']:
                modify_info.append(f'wallpaper: {attr_dict["wallpaper"]}')
            modify_info += [f'{attr}: {getattr(useroj, attr)}->{attr_dict[attr]}'
                            for attr in attr_check_list
                            if (attr_dict[attr] != "" and str(getattr(useroj, attr)) != attr_dict[attr])]
            modify_info += [f'{show_attr}: {getattr(useroj, show_attr)}->{show_dict[show_attr]}'
                            for show_attr in show_dict.keys()
                            if getattr(useroj, show_attr) != show_dict[show_attr]]

            if attr_dict['gender'] != useroj.gender:
                useroj.gender = NaturalPerson.Gender.MALE if attr_dict['gender'] == '男' else NaturalPerson.Gender.FEMALE
            if attr_dict['wechat_receive_level'] != useroj.wechat_receive_level:
                useroj.wechat_receive_level = NaturalPerson.ReceiveLevel.MORE if attr_dict['wechat_receive_level'] == '接受全部消息' else NaturalPerson.ReceiveLevel.LESS
            if attr_dict['accept_promote'] != useroj.get_accept_promote_display():
                useroj.accept_promote = True if attr_dict['accept_promote'] == '是' else False
            for attr in attr_check_list:
                if attr_dict[attr] != "" and str(getattr(useroj, attr)) != attr_dict[attr]:
                    setattr(useroj, attr, attr_dict[attr])
            for show_attr in show_dict.keys():
                if getattr(useroj, show_attr) != show_dict[show_attr]:
                    setattr(useroj, show_attr, show_dict[show_attr])
            if 'ava' in attr_dict.keys() and attr_dict['ava'] is not None:
                useroj.avatar = attr_dict['ava']
            if 'wallpaper' in attr_dict.keys() and attr_dict['wallpaper'] is not None:
                useroj.wallpaper = attr_dict['wallpaper']
            expr = len(modify_info)
            if expr >= 1:
                useroj.save()
                upload_state = True
                modify_msg = '\n'.join(modify_info)
                record_modify_with_session(request,
                    f"修改了{expr}项信息：\n{modify_msg}")
                return redirect("/stuinfo/?modinfo=success")
            # else: 没有更新

        return render(request, "person_account_setting.html", locals())

    else:
        info = Organization.objects.filter(organization_id=user)
        userinfo = info.values()[0]

        useroj = Organization.objects.get(organization_id=user)
        former_wallpaper = utils.get_user_wallpaper(me, "Organization")
        org_tags = list(useroj.tags.all())
        all_tags = list(OrganizationTag.objects.all())
        if request.method == "POST" and request.POST:

            ava = request.FILES.get("avatar")
            wallpaper = request.FILES.get("wallpaper")
            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(request, user_type)
            attr_check_list = [attr for attr in attr_dict.keys()]
            if html_display['warn_code'] == 1:
                return render(request, "person_account_setting.html", locals())

            modify_info = []
            if ava:
                modify_info.append(f'avatar: {ava}')
            if wallpaper:
                modify_info.append(f'wallpaper: {wallpaper}')
            attr = 'introduction'
            if (attr_dict[attr] != "" and str(getattr(useroj, attr)) != attr_dict[attr]):
                modify_info += [f'{attr}: {getattr(useroj, attr)}->{attr_dict[attr]}']
            attr = 'tags_modify'
            if attr_dict[attr] != "":
                modify_info += [f'{attr}: {attr_dict[attr]}']

            attr = 'introduction'
            if attr_dict[attr] != "" and str(getattr(useroj, attr)) != attr_dict[attr]:
                setattr(useroj, attr, attr_dict[attr])
            if attr_dict['tags_modify'] != "":
                for modify in attr_dict['tags_modify'].split(';'):
                    if modify != "":
                        action, tag_name = modify.split(" ")
                        if action == 'add':
                            useroj.tags.add(OrganizationTag.objects.get(name=tag_name))
                        else:
                            useroj.tags.remove(OrganizationTag.objects.get(name=tag_name))
            if ava is None:
                pass
            else:
                useroj.avatar = ava
            if wallpaper is not None:
                useroj.wallpaper = wallpaper
            useroj.save()
            avatar_path = MEDIA_URL + str(ava)
            expr = len(modify_info)
            if expr >= 1:
                upload_state = True
                modify_msg = '\n'.join(modify_info)
                record_modify_with_session(request,
                    f"修改了{expr}项信息：\n{modify_msg}")
                return redirect("/orginfo/?modinfo=success")
            # else: 没有更新

        return render(request, "org_account_setting.html", locals())


@log.except_captured(source='views[freshman]', record_user=True,
                     record_request_args=True, show_traceback=True)
def freshman(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect(message_url(wrong('你已经登录，无需进行注册!')))

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


@login_required(redirect_field_name="origin")
@log.except_captured(source='views[userAgreement]', record_user=True)
def userAgreement(request: HttpRequest):
    # 不要加check_user_access，因为本页面就是该包装器首次登录时的跳转页面之一
    valid, user_type, html_display = utils.check_user_type(request.user)
    if not valid:
        return redirect("/index/")

    if request.method == "POST":
        confirm = request.POST.get('confirm') == 'yes'
        if not confirm:
            return redirect('/logout/')
        request.session['confirmed'] = 'yes'
        return redirect('/modpw/')

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "用户须知")
    return render(request, 'user_agreement.html', locals())



@log.except_captured(source='views[authRegister]', record_user=True)
def authRegister(request: HttpRequest):
    if request.user.is_superuser:
        if request.method == "POST" and request.POST:
            name = request.POST["name"]
            password = request.POST["password"]
            sno = request.POST["snum"]
            email = request.POST["email"]
            password2 = request.POST["password2"]
            stu_grade = request.POST["syear"]
            gender = request.POST['sgender']
            if password != password2:
                return render(request, "index.html")
            else:
                if gender not in ['男', '女']:
                    return render(request, "auth_register_boxed.html")
                # user with same sno
                same_user = NaturalPerson.objects.filter(person_id=sno)
                if same_user:
                    return render(request, "auth_register_boxed.html")
                same_email = NaturalPerson.objects.filter(email=email)
                if same_email:
                    return render(request, "auth_register_boxed.html")

                # OK!
                try:
                    user = User.objects.create_user(username=sno, password=password)
                except:
                    # 存在用户
                    return HttpResponseRedirect("/admin/")

                try:
                    new_user = NaturalPerson.objects.create(
                        person_id=user,
                        stu_id_dbonly=sno,
                        name = name,
                        email = email,
                        stu_grade = stu_grade,
                        gender = NaturalPerson.Gender.MALE if gender == '男'\
                            else NaturalPerson.Gender.FEMALE,
                    )
                except:
                    # 创建失败，把创建的用户删掉
                    return HttpResponseRedirect("/admin/")
                return HttpResponseRedirect("/index/")
        return render(request, "auth_register_boxed.html")
    else:
        return HttpResponseRedirect("/index/")


# @login_required(redirect_field_name=None)
@log.except_captured(source='views[logout]', record_user=True)
def logout(request: HttpRequest):
    auth.logout(request)
    return HttpResponseRedirect("/index/")


"""
@log.except_captured(source='views[org_spec]', record_user=True)
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

@log.except_captured(source='views[get_stu_img]', record_user=True)
def get_stu_img(request: HttpRequest):
    if DEBUG: print("in get stu img")
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
@log.except_captured(source='views[search]', record_user=True)
def search(request: HttpRequest):
    """
        搜索界面的呈现逻辑
        分成搜索个人和搜索小组两个模块，每个模块的呈现独立开，有内容才呈现，否则不显示
        搜索个人：
            支持使用姓名搜索，支持对未设为不可见的昵称和专业搜索
            搜索结果的呈现采用内容/未公开表示，所有列表为people_filed
        搜索小组
            支持使用小组名、小组类型搜索、一级负责人姓名
            小组的呈现内容由拓展表体现，不在这个界面呈现具体成员
            add by syb:
            支持通过小组名、小组类型来搜索小组
            支持通过公开关系的个人搜索小组，即如果某自然人用户可以被上面的人员搜索检出，
            而且该用户选择公开其与小组的关系，那么该小组将在搜索界面呈现。
            搜索结果的呈现内容见organization_field
        搜索活动
            支持通过活动名、小组来搜索活动。只要可以搜索到小组，小组对应的活动就也可以被搜到
            搜索结果的呈现见activity_field
    """

    valid, user_type, html_display = utils.check_user_type(request.user)

    query = request.GET.get("Query", "")
    if query == "":
        return redirect(message_url(wrong('请填写有效的搜索信息!')))

    not_found_message = "找不到符合搜索的信息或相关内容未公开！"
    # 首先搜索个人, 允许搜索姓名或者公开的专业, 删去小名搜索
    people_list = NaturalPerson.objects.filter(
        Q(name__icontains=query)
        | (  # (Q(nickname__icontains=query) & Q(show_nickname=True)) |
                Q(stu_major__icontains=query) & Q(show_major=True)
        )
        | (
            Q(nickname__icontains=query) & Q(show_nickname=True)
        )
    )

    # 接下来准备呈现的内容
    # 首先是准备搜索个人信息的部分
    people_field = [
        "姓名",
        "昵称",
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

    # 搜索小组
    # 先查找query作为姓名包含在字段中的职务信息, 选的是post为true或者职务等级为0
    pos_list = Position.objects.activated().filter(person__name__icontains=query).filter(
        Q(show_post=True) | Q(is_admin=True))
    # 通过小组名、小组类名、和上述的职务信息对应的小组信息
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
                    id__in=Position.objects.activated().filter(is_admin=True, org=org).values("person")
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

    # 小组要呈现的具体内容
    organization_field = ["小组名称", "小组类型", "负责人", "近期活动"]

    # 搜索活动
    activity_list = Activity.objects.activated().filter(
        Q(title__icontains=query) | Q(organization_id__oname__icontains=query)& ~Q(status=Activity.Status.CANCELED)
                                                         & ~Q(status=Activity.Status.REJECT)
        &~Q(status=Activity.Status.REVIEWING)&~Q(status=Activity.Status.ABORT)
    )

    # 活动要呈现的内容
    activity_field = ["活动名称", "承办小组", "状态"]

    feedback_field = ["标题", "状态", "负责小组", "内容"]
    feedback_list = Feedback.objects.filter(
        Q(public_status=Feedback.PublicStatus.PUBLIC)
    ).filter(
        Q(title__icontains=query) 
        | Q(org__oname__icontains=query)
    )

    me = get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "信息搜索")
    # bar_display["title_name"] = "Search"
    # bar_display["navbar_name"] = "信息搜索"  #

    return render(request, "search.html", locals())


@log.except_captured(source='views[forgetPassword]', record_user=True,
                     record_request_args=True, show_traceback=True)
def forgetPassword(request: HttpRequest):
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
                display = wrong("暂不支持小组账号验证码登录！")
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
                    utils.update_related_account_in_session(request, user.username)
                    utils.clear_captcha_session(request)
                    # request.session["username"] = username 已废弃
                    request.session["forgetpw"] = "yes"
                    return redirect(reverse("modpw"))
                else:
                    display = wrong("验证码错误")
                display.setdefault("colddown", 30)
    return render(request, "forget_password.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/", is_modpw=True)
@log.except_captured(source='views[modpw]', record_user=True)
def modpw(request: HttpRequest):
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
    me = get_person_or_org(request.user, user_type)
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
        min_length = 8
        try:
            if oldpassword == newpw and strict_check and not (forgetpw or isFirst):
                raise ValidationError(message="新密码不能与原密码相同")
            elif newpw == username and strict_check:
                raise ValidationError(message="新密码不能与学号相同")
            elif newpw != oldpassword and (forgetpw or isFirst):  # added by pht
                raise ValidationError(message="两次输入的密码不匹配")
            elif len(newpw) < min_length:
                raise ValidationError(message=f"新密码不能短于{min_length}位")
            if strict_check:
                NumericPasswordValidator().validate(password=newpw)
                CommonPasswordValidator().validate(password=newpw)
        except ValidationError as e:
            err_code = 1
            err_message = e.message
        # if oldpassword == newpw and strict_check and not (forgetpw or isFirst):
        #     err_code = 1
        #     err_message = "新密码不能与原密码相同"
        # elif newpw == username and strict_check:
        #     err_code = 2
        #     err_message = "新密码不能与学号相同"
        # elif newpw != oldpassword and (forgetpw or isFirst):  # added by pht
        #     err_code = 5
        #     err_message = "两次输入的密码不匹配"
        # elif len(newpw) < min_length:
        #     err_code = 6
        # err_message = f"新密码的长度不能少于{min_length}位"
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

                    # record_modify_with_session(request,
                    #     "首次修改密码" if isFirst else "修改密码")
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



@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[subscribeOrganization]', record_user=True)
def subscribeOrganization(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type != UTYPE_PER:
        succeed('小组账号不支持订阅，您可以在此查看小组列表！', html_display)
        html_display.update(readonly=True)

    me = get_person_or_org(request.user, user_type)
    # orgava_list = [(org, utils.get_user_ava(org, "Organization")) for org in org_list]
    otype_infos = [(
        otype,
        list(Organization.objects.filter(otype=otype)
            .select_related("organization_id")),
    ) for otype in OrganizationType.objects.all().order_by('-otype_id')]

    # 获取不订阅列表（数据库里的是不订阅列表）
    if user_type == UTYPE_PER:
        unsubscribe_set = set(me.unsubscribe_list.values_list(
            'organization_id__username', flat=True))
    else:
        unsubscribe_set = set(Organization.objects.values_list(
            'organization_id__username', flat=True))

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 小组暂且不使用订阅提示
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name='我的订阅' if user_type == UTYPE_PER else '小组一览')

    # all_number = NaturalPerson.objects.activated().all().count()    # 人数全体 优化查询
    return render(request, "organization_subscribe.html", locals())




@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[saveSubscribeStatus]', record_user=True)
def saveSubscribeStatus(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type != UTYPE_PER:
        return JsonResponse({"success":False})

    me = get_person_or_org(request.user, user_type)
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
        # elif "level" in params.keys():
        #     try:
        #         level = params['level']
        #         assert level in ['less', 'more']
        #     except:
        #         return JsonResponse({"success":False})
        #     me.wechat_receive_level = (
        #         NaturalPerson.ReceiveLevel.MORE
        #         if level == 'more' else
        #         NaturalPerson.ReceiveLevel.LESS
        #     )
        me.save()

    return JsonResponse({"success": True})

'''
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[apply_position]', record_user=True)
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

    me = get_person_or_org(request.user, user_type)
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
        return redirect(f"/orginfo/?name={org.oname}&warn_code=1&warn_message={e}")

    contents = [f"{apply_type}申请已提交审核", f"{apply_type}申请审核"]
    notification_create(
        me.person_id,
        org.organization_id,
        Notification.Type.NEEDREAD,
        Notification.Title.POSITION_INFORM,
        contents[0],
        "/personnelMobilization/",
        publish_to_wechat=True,  # 不要复制这个参数，先去看函数说明
        publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
    )
    notification_create(
        org.organization_id,
        me.person_id,
        Notification.Type.NEEDDO,
        Notification.Title.POSITION_INFORM,
        contents[1],
        "/personnelMobilization/",
        publish_to_wechat=True,  # 不要复制这个参数，先去看函数说明
        publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.IMPORTANT},
    )
    return redirect("/notifications/")
'''


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[notifications]', record_user=True)
def notifications(request: HttpRequest):
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

    me = get_person_or_org(request.user, user_type)
    html_display["is_myself"] = True

    notification_set = Notification.objects.activated().select_related(
        'sender').filter(receiver=request.user)

    done_list = notification2Display(notification_set.order_by("-finish_time"))

    undone_list = notification2Display(notification_set.order_by("-start_time"))

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="通知信箱")
    return render(request, "notifications.html", locals())




@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[QAcenter]', record_user=True)
def QAcenter(request: HttpRequest):
    """
    Haowei:
    QA的聚合界面
    """
    valid, user_type, html_display = utils.check_user_type(request.user)

    me = get_person_or_org(request.user, user_type)

    if request.method == "POST":
        if request.POST.get("anwser") is not None:
            anwser = request.POST.get("anwser")
            if len(anwser) == 0:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "请填写回答再提交！"
            else:
                QA_anwser(request.POST.get("id"), anwser)
                html_display["warn_code"] = 2
                html_display["warn_message"] = "成功提交该问题的回答！"
        else:
            post_args = json.loads(request.body.decode("utf-8"))
            if 'cancel' in post_args['function']:
                try:
                    QA_delete(int(post_args['id']))
                    html_display['warn_code'] = 2
                    html_display['warn_message'] = "成功删除一条提问！"
                    return JsonResponse({"success":True})
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "在设置提问状态为「忽略」的过程中出现了未知错误，请联系管理员！"
                    return JsonResponse({"success":False})
            else:
                try:
                    QA_ignore(int(post_args['id']), \
                        sender_flag=(post_args['function'] == 'sender')
                        )
                    html_display['warn_code'] = 2
                    html_display['warn_message'] = "成功忽略一条提问！"
                    return JsonResponse({"success":True})
                except:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = "在设置提问状态为「忽略」的过程中出现了未知错误，请联系管理员！"
                    return JsonResponse({"success":False})


    all_instances = QA2Display(request.user)

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="问答中心")
    return render(request, "QandA_center.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, log=False)
def eventTrackingFunc(request: HttpRequest):
    # unpack request:
    logType = int(request.POST['Type'])
    logUrl = request.POST['Url']
    try:
        logTime = int(request.POST['Time'])
        logTime = datetime.fromtimestamp(logTime / 1000)
    except:
        logTime = datetime.now()
    # 由于对PV/PD埋点的JavaScript脚本在base.html中实现，所以所有页面的PV/PD都会被track
    logPlatform = request.POST.get('Platform', None)
    try:
        logExploreName, logExploreVer = request.POST['Explore'].rsplit(maxsplit=1)
    except:
        logExploreName, logExploreVer = None, None

    kwargs = {}
    kwargs.update(
        user=request.user,
        type=logType,
        page=logUrl,
        time=logTime,
        platform=logPlatform,
        explore_name=logExploreName,
        explore_version=logExploreVer,
    )
    if logType in ModuleLog.CountType.values:
        # Module类埋点
        kwargs.update(
            module_name=request.POST['Name'],
        )
        ModuleLog.objects.create(**kwargs)
    elif logType in PageLog.CountType.values:
        # Page类的埋点
        PageLog.objects.create(**kwargs)

    return JsonResponse({'status': 'ok'})
