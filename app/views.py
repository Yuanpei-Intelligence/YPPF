import json
import random
import requests
from datetime import datetime, timedelta

from django.contrib import auth
from django.db import transaction
from django.db.models import Q, F, Sum, QuerySet
from django.contrib.auth.password_validation import CommonPasswordValidator, NumericPasswordValidator
from django.core.exceptions import ValidationError

from utils.config.cast import str_to_time
from utils.hasher import MyMD5Hasher
from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Freshman,
    Position,
    AcademicTag,
    AcademicTextEntry,
    Organization,
    OrganizationTag,
    OrganizationType,
    Activity,
    ActivityPhoto,
    Participant,
    Notification,
    Wishes,
    Course,
    CourseRecord,
    Semester,
    AcademicQA,
)
from app.utils import (
    get_person_or_org,
    record_modify_with_session,
    update_related_account_in_session,
)
from extern.wechat import (
    send_verify_code,
    invite_to_wechat,
)
from app.notification_utils import (
    notification_status_change,
    notification2Display,
)
from app.YQPoint_utils import add_signin_point, update_YQMM
from app.academic_utils import (
    get_search_results,
    comments2Display,
    get_js_tag_list,
    get_text_list,
    have_entries_of_type,
    get_tag_status,
    get_text_status,
)



@login_required(redirect_field_name="origin")
@logger.secure_view()
def shiftAccount(request: HttpRequest):

    username = request.session.get("NP")
    if not username:
        return redirect(message_url(wrong('没有可切换的账户信息，请重新登录!')))

    oname = ""
    if request.method == "GET" and request.GET.get("oname"):
        oname = request.GET["oname"]

    # 不一定更新成功，但无所谓
    update_related_account_in_session(
        request, username, shift=True, oname=oname)

    if request.method == "GET" and request.GET.get("origin"):
        arg_url = request.GET["origin"]
        if arg_url.startswith('/'):  # 暂时只允许内部链接
            return redirect(arg_url)
    return redirect("/welcome/")


# Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5Hasher("wechat_login")


@logger.secure_view()
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
            en_pw = GLOBAL_CONFIG.hasher.encode(username)
            user_account = NaturalPerson.objects.get(person_id=username)
            return JsonResponse({"Sname": user_account.name, "Succeed": 1}, status=200)
        else:
            return JsonResponse({"Sname": username, "Succeed": 0}, status=400)
    except:
        return JsonResponse({"Sname": "", "Succeed": 0}, status=400)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def stuinfo(request: UserRequest):
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

    html_display = {}

    oneself = get_person_or_org(request.user)

    name = request.GET.get('name', None)
    if name is None:
        if request.user.is_org():
            return redirect("/orginfo/")  # 小组只能指定学生姓名访问
        else:  # 跳轉到自己的頁面
            assert request.user.is_person()
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
                if request.user.is_person() and oneself.name == name:
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

        is_myself = person.get_user() == request.user
        inform_share, alert_message = utils.get_inform_share(
            me=person, is_myself=is_myself)

        # 处理更改数据库中inform_share的post
        if request.method == "POST" and request.POST:
            option = request.POST.get("option", "")
            assert option == "cancelInformShare" and is_myself
            person.inform_share = False
            person.save()
            return redirect("/welcome/")

        # ----------------------------------- 小组卡片 ----------------------------------- #

        def _get_org_latest_pos(positions: QuerySet[Position], org):
            '''同一组织可能关联多个职位导致的bug，暂用于修复'''
            # TODO: 重写职位呈现逻辑，减少数据库访问
            return positions.filter(org=org).order_by('year', 'semester').last()

        person_poss = Position.objects.activated().filter(Q(person=person))
        person_orgs: QuerySet[Organization] = Organization.objects.filter(
            id__in=person_poss.values("org")
        )  # ta属于的小组
        oneself_orgs = (
            [oneself]
            if request.user.is_org()
            else Position.objects.activated().filter(
                Q(person=oneself) & Q(show_post=True)
            )
        )
        oneself_orgs_id = [
            oneself.id] if request.user.is_org() else oneself_orgs.values("org")  # 自己的小组

        # 当前管理的小组
        person_owned_poss = person_poss.filter(
            is_admin=True, status=Position.Status.INSERVICE)
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

        # 当前属于的小组
        person_joined_poss = person_poss.filter(
            ~Q(is_admin=True) & Q(show_post=True))
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
        person_history_orgs: QuerySet[Organization] = Organization.objects.filter(
            id__in=person_history_poss.values("org")
        )  # ta属于的小组
        person_history_orgs_ava = [
            # utils.get_user_ava(org, "organization") for org in person_owned_orgs
            org.get_user_ava() for org in person_history_orgs
        ]
        person_history_orgs_poss = [
            _get_org_latest_pos(person_history_poss, org) for org in person_history_orgs
        ]  # ta在小组中的职位对象

        sems = {
            Semester.FALL: "秋",
            Semester.SPRING: "春",
            Semester.ANNUAL: "全年"
        }

        person_history_orgs_pos = [
            org.otype.get_name(pos.pos) + ' ' +
            str(pos.year)[2:] + "-" +
            str(pos.year + 1)[2:] +
            sems[pos.semester]
            for pos, org in zip(person_history_orgs_poss, person_history_orgs)
        ]  # ta在小组中的职位
        html_display["history_orgs_info"] = (
            list(zip(person_history_orgs, person_history_orgs_ava,
                 person_history_orgs_pos))
            or None
        )

        # 隐藏的小组(所有学期都会呈现，不用activated)
        person_hidden_poss = Position.objects.filter(
            person=person, show_post=False)
        person_hidden_orgs: QuerySet[Organization] = Organization.objects.filter(
            id__in=person_hidden_poss.values("org")
        )  # ta属于的小组
        person_hidden_orgs_ava = [
            org.get_user_ava() for org in person_hidden_orgs
        ]  # ta在小组中的职位
        person_hidden_orgs_pos = [
            org.otype.get_name(_get_org_latest_pos(
                person_hidden_poss, org).pos)
            for org in person_hidden_orgs
        ]  # ta在小组中的职位
        person_hidden_orgs_status = [
            _get_org_latest_pos(person_hidden_poss, org).status for org in person_hidden_orgs
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
            for course_type in list(Course.CourseType):  # CourseType.values亦可
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
        if request.user.is_person():
            # 因为上面筛选过活动，这里就不用筛选了
            # 之前那个写法是O(nm)的
            activities_me = Participant.objects.activated().filter(person_id=oneself)
            activities_me = set(activities_me.values_list(
                "activity_id_id", flat=True))
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

        my_messages.transfer_message_context(request.GET, html_display)
        if request.GET.get("modinfo", "") == "success":
            succeed("修改个人信息成功!", html_display)

        # ----------------------------------- 学术地图 ----------------------------------- #
        # ------------------ 提问区 or 进行中的问答------------------ #
        progressing_chat = AcademicQA.objects.activated().filter(
            directed=True,
            chat__questioner=request.user,
            chat__respondent=person.get_user()
        )
        if progressing_chat.exists():
            comments2Display(progressing_chat.first().chat, html_display, request.user)  # TODO: 字典的key有冲突风险
            html_display["have_progressing_chat"] = True
        else:  # 没有进行中的问答，显示提问区
            html_display["have_progressing_chat"] = False
            html_display["accept_chat"] = person.get_user().accept_chat
            html_display["accept_anonymous"] = person.get_user().accept_anonymous_chat

        # 存储被查询人的信息
        context = dict()

        context["person"] = person

        context["title"] = "我" if is_myself else (
            {0: "他", 1: "她"}.get(person.gender, 'Ta') if person.show_gender else "Ta")

        context["avatar_path"] = person.get_user_ava()
        context["wallpaper_path"] = utils.get_user_wallpaper(person)

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display
        bar_display = utils.get_sidebar_and_navbar(
            request.user, navbar_name="个人主页", title_name=person.name
        )
        origin = request.get_full_path()

        if request.session.get('alert_message'):
            load_alert_message = request.session.pop('alert_message')

        # 浏览次数，必须在render之前
        # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
        NaturalPerson.objects.filter(id=person.id).update(
            visit_times=F('visit_times')+1)
        # person.visit_times += 1
        # person.save()

        # ------------------ 查看学术地图 ------------------ #
        academic_params = {"author_id": person.person_id_id}
        # 下面准备前端展示量
        status_in = None
        if is_myself:
            academic_params["user_type"] = "author"
        elif request.user.is_person() and oneself.is_teacher():
            academic_params["user_type"] = "inspector"
            status_in = ['public', 'wait_audit']
        else:
            academic_params["user_type"] = "viewer"
            status_in = ['public']

        # 判断用户是否有可以展示的内容
        if academic_params["user_type"] == "viewer":
            academic_params["have_content"] = have_entries_of_type(person, [
                                                                   "public"])
        else:
            academic_params["have_content"] = have_entries_of_type(
                person, ["public", "wait_audit"])
        academic_params["have_unaudit"] = have_entries_of_type(person, [
                                                               "wait_audit"])

        # 获取用户已有的专业/项目的列表，用于select的默认选中项
        academic_params.update(
            selected_major_list=get_js_tag_list(person, AcademicTag.Type.MAJOR,
                                                selected=True, status_in=status_in),
            selected_minor_list=get_js_tag_list(person, AcademicTag.Type.MINOR,
                                                selected=True, status_in=status_in),
            selected_double_degree_list=get_js_tag_list(person, AcademicTag.Type.DOUBLE_DEGREE,
                                                        selected=True, status_in=status_in),
            selected_project_list=get_js_tag_list(person, AcademicTag.Type.PROJECT,
                                                  selected=True, status_in=status_in),
        )

        # 获取用户已有的TextEntry的contents，用于TextEntry填写栏的前端预填写
        scientific_research_list = get_text_list(
            person, AcademicTextEntry.Type.SCIENTIFIC_RESEARCH, status_in
        )
        challenge_cup_list = get_text_list(
            person, AcademicTextEntry.Type.CHALLENGE_CUP, status_in
        )
        internship_list = get_text_list(
            person, AcademicTextEntry.Type.INTERNSHIP, status_in
        )
        scientific_direction_list = get_text_list(
            person, AcademicTextEntry.Type.SCIENTIFIC_DIRECTION, status_in
        )
        graduation_list = get_text_list(
            person, AcademicTextEntry.Type.GRADUATION, status_in
        )
        academic_params.update(
            scientific_research_list=scientific_research_list,
            challenge_cup_list=challenge_cup_list,
            internship_list=internship_list,
            scientific_direction_list=scientific_direction_list,
            graduation_list=graduation_list,
            scientific_research_num=len(scientific_research_list),
            challenge_cup_num=len(challenge_cup_list),
            internship_num=len(internship_list),
            scientific_direction_num=len(scientific_direction_list),
            graduation_num=len(graduation_list),
        )

        # 最后获取每一种atype对应的entry的公开状态，如果没有则默认为公开
        major_status = get_tag_status(person, AcademicTag.Type.MAJOR)
        minor_status = get_tag_status(person, AcademicTag.Type.MINOR)
        double_degree_status = get_tag_status(
            person, AcademicTag.Type.DOUBLE_DEGREE)
        project_status = get_tag_status(person, AcademicTag.Type.PROJECT)
        scientific_research_status = get_text_status(
            person, AcademicTextEntry.Type.SCIENTIFIC_RESEARCH
        )
        challenge_cup_status = get_text_status(
            person, AcademicTextEntry.Type.CHALLENGE_CUP
        )
        internship_status = get_text_status(
            person, AcademicTextEntry.Type.INTERNSHIP
        )
        scientific_direction_status = get_text_status(
            person, AcademicTextEntry.Type.SCIENTIFIC_DIRECTION
        )
        graduation_status = get_text_status(
            person, AcademicTextEntry.Type.GRADUATION
        )

        status_dict = dict(
            major_status=major_status,
            minor_status=minor_status,
            double_degree_status=double_degree_status,
            project_status=project_status,
            scientific_research_status=scientific_research_status,
            challenge_cup_status=challenge_cup_status,
            internship_status=internship_status,
            scientific_direction_status=scientific_direction_status,
            graduation_status=graduation_status,
        )
        academic_params.update(status_dict)

        # is_myself是内部变量，不传给前端
        html_display["is_myself"] = is_myself
        return render(request, "stuinfo.html", locals() | dict(user=request.user))


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def requestLoginOrg(request: UserRequest):
    """
        这个函数的逻辑是，个人账户点击左侧的管理小组直接跳转登录到小组账户
        首先检查登录的user是个人账户，否则直接跳转orginfo
        如果个人账户对应的是name对应的小组的最高权限人，那么允许登录，否则跳转回stuinfo并warning
    """
    if request.user.is_org():
        return redirect("/orginfo/")
    try:
        me = NaturalPerson.objects.activated().get(person_id=request.user)
    except:  # 找不到合法的用户
        return redirect(message_url(wrong('用户不存在!')))
    name = request.GET.get('name')
    if name is None:  # 个人登录未指定登入小组,属于不合法行为,弹回欢迎
        return redirect(message_url(wrong('无效的小组信息!')))
    # 确认有无这个小组
    try:
        org: Organization = Organization.objects.get(oname=name)
    except:  # 找不到对应小组
        return redirect(message_url(wrong('找不到对应小组,请联系管理员!'),
                                    me.get_absolute_url()))
    try:
        position = Position.objects.activated().filter(org=org, person=me)
        assert len(position) == 1
        position = position[0]
        assert position.is_admin == True
    except:
        return redirect(message_url(wrong('没有登录到该小组账户的权限!'),
                                    me.get_absolute_url()))
    # 到这里,是本人小组并且有权限登录
    auth.logout(request)
    auth.login(request, org.get_user())  # 切换到小组账号
    update_related_account_in_session(
        request, request.user.username, oname=org.oname)
    return redirect(message_url(succeed(f'成功切换到{org}的账号!'), '/orginfo/'))


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def orginfo(request: UserRequest):
    """
        orginfo负责呈现小组主页，逻辑和stuinfo是一样的，可以参考
        只区分自然人和法人，不区分自然人里的负责人和非负责人。任何自然人看这个小组界面都是【不可管理/编辑小组信息】
    """
    name = request.GET.get('name', None)
    if name is None:  # 此时登陆的必需是法人账号，如果是自然人，则跳转welcome
        if request.user.is_person():
            return redirect(message_url(wrong('个人账号不能登陆小组主页!')))
        try:
            org = Organization.objects.activated().get(organization_id=request.user)
        except:
            return redirect(message_url(wrong('用户小组不存在或已经失效!')))

        full_path = request.get_full_path()
        append_url = "" if ("?" not in full_path) else "&" + \
            full_path.split("?")[1]

        return redirect(org.get_absolute_url() + append_url)

    try:
        # 下面是小组信息
        org = Organization.objects.activated().get(oname=name)
        org_tags = org.tags.all()
    except:
        return redirect(message_url(wrong('该小组不存在!')))

    # 指定名字访问小组账号的，可以是自然人也可以是法人。在html里要注意区分！
    # 判断是否为小组账户本身在登录
    is_myself = org.get_user() == request.user
    me = get_person_or_org(request.user)

    html_display = {}
    html_display["is_myself"] = is_myself
    html_display["is_course"] = (
        Course.objects.activated().filter(organization=org).exists()
    )
    inform_share, alert_message = utils.get_inform_share(me, is_myself=is_myself)

    organization_name = name
    organization_type_name = org.otype.otype_name
    org_avatar_path = org.get_user_ava()
    wallpaper_path = utils.get_user_wallpaper(org)
    # org的属性 information 不在此赘述，直接在前端调用

    # 给前端传递选课的参数
    yx_election_start = CONFIG.course.yx_election_start
    yx_election_end = CONFIG.course.yx_election_end
    if (str_to_time(yx_election_start) <= datetime.now() < (
            str_to_time(yx_election_end))):
        html_display["select_ing"] = True
    else:
        html_display["select_ing"] = False

    if request.method == "POST":
        if request.POST.get("export_excel") is not None and is_myself:
            return utils.export_orgpos_info(org)
        elif request.POST.get("option", "") == "cancelInformShare" and is_myself:
            org.inform_share = False
            org.save()
            return redirect("/welcome/")

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
        dictmp["endbefore"] = act.start - \
            timedelta(hours=prepare_times[act.endbefore])
        if request.user.is_person():

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
        if request.user.is_person():
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
        dictmp["endbefore"] = act.start - \
            timedelta(hours=prepare_times[act.endbefore])
        if request.user.is_person():
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
        if p.person.person_id == request.user and p.pos == 0:
            html_display["isboss"] = True
        if p.show_post == True or p.pos == 0 or is_myself:
            member = {}
            member['show_post'] = p.show_post
            member['id'] = p.id
            member["person"] = p.person
            member["job"] = org.otype.get_name(p.pos)
            member["highest"] = True if p.pos == 0 else False

            member["avatar_path"] = p.person.get_user_ava()

            member_list.append(member)

    my_messages.transfer_message_context(request.GET, html_display)
    if request.GET.get("modinfo", "") == "success":
        succeed("修改小组信息成功!", html_display)

    # 小组活动的信息

    # 补充一些呈现信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="小组主页", title_name=org.oname)
    # 转账后跳转
    origin = request.get_full_path()

    # 补充订阅该小组的按钮
    allow_unsubscribe = org.otype.allow_unsubscribe  # 是否允许取关
    if request.user.is_person():
        _unsubscribe_names = me.unsubscribe_list.values_list("oname", flat=True)
        subscribe_flag = organization_name not in _unsubscribe_names

    # 补充作为小组成员，选择是否展示的按钮
    show_post_change_button = False     # 前端展示“是否不展示我自己”的按钮，若为True则渲染这个按钮
    if request.user.is_person():
        my_position = Position.objects.activated().filter(
            org=org, person=me).exclude(is_admin=True).first()
        show_post_change_button = my_position is not None

    if request.session.get('alert_message'):
        load_alert_message = request.session.pop('alert_message')

    # 浏览次数，必须在render之前
    # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
    Organization.objects.filter(id=org.id).update(
        visit_times=F('visit_times')+1)
    return render(request, "orginfo.html", locals() | dict(user=request.user))


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def homepage(request: UserRequest):
    html_display = {}
    my_messages.transfer_message_context(request.GET, html_display)

    nowtime = datetime.now()
    # 今天第一次访问 welcome 界面，积分增加
    if request.user.is_person():
        with transaction.atomic():
            np: NaturalPerson = NaturalPerson.objects.select_for_update().get(
                person_id=request.user)
            if np.last_time_login is None or np.last_time_login.date() != nowtime.date():
                np.last_time_login = nowtime
                np.save()
                add_point, html_display['signin_display'] = add_signin_point(
                    request.user)
                html_display['first_signin'] = True  # 前端显示

    # 元气满满系列更新
    # TODO: 与设置中学期开始的时间同步，暂时没找到接口
    semester_start = datetime(2023, 8, 19, 0, 0, 0)
    html_display['YQMM'] = update_YQMM(request.user, semester_start)

    # 开始时间在前后一周内，除了取消和审核中的活动。按时间逆序排序
    recentactivity_list = Activity.objects.get_recent_activity(
    ).select_related('organization_id')

    # 开始时间在今天的活动,且不展示结束的活动。按开始时间由近到远排序
    activities = Activity.objects.get_today_activity().select_related('organization_id')
    activities_start = [
        activity.start.strftime("%H:%M") for activity in activities
    ]
    html_display['today_activities'] = list(
        zip(activities, activities_start)) or None

    # 最新一周内发布的活动，按发布的时间逆序
    newlyreleased_list = Activity.objects.get_newlyreleased_activity(
    ).select_related('organization_id')

    # 即将截止的活动，按截止时间正序
    prepare_times = Activity.EndBeforeHours.prepare_times

    signup_list = []
    signup_rec = Activity.objects.activated().select_related(
        'organization_id').filter(status=Activity.Status.APPLYING).order_by("category", "apply_end")[:10]
    for act in signup_rec:
        deadline = act.apply_end
        dictmp = {}
        dictmp["deadline"] = deadline
        dictmp["act"] = act
        dictmp["tobestart"] = (deadline - nowtime).total_seconds()//360/10
        signup_list.append(dictmp)

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
        new_wish = Wishes.objects.create(text=wishtext, background=background)
        new_wish.save()

    # 心愿墙！！！！!最近一周的心愿，已经逆序排列，如果超过100个取前100个就可
    wishes = Wishes.objects.filter(
        time__gt=nowtime - timedelta(days=7)
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
    all_photo_display = ActivityPhoto.objects.filter(
        type=ActivityPhoto.PhotoType.SUMMARY).order_by('-time')
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
    # TODO: Put get_weather somewhere else
    from app.jobs import get_weather
    _weather = get_weather()
    if _weather.get('modify_time') is None:
        update_time_delta = timedelta(0)
    else:
        update_time_delta = datetime.now() - datetime.strptime(
            _weather['modify_time'],'%Y-%m-%d %H:%M:%S.%f')
    html_display['weather'] = _weather
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
    # -------------------------------天气结束-------------------------

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "元培生活")
    # bar_display["title_name"] = "Welcome Page"
    # bar_display["navbar_name"] = "元培生活"

    return render(request, "welcome_page.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def accountSetting(request: UserRequest):
    html_display = {}

    # 在这个页面 默认回归为自己的左边栏
    user = request.user
    me = get_person_or_org(request.user)
    former_img = utils.get_user_ava(me)

    # 补充网页呈现所需信息
    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "信息与隐私")
    # bar_display["title_name"] = "Account Setting"
    # bar_display["navbar_name"] = "账户设置"

    if request.user.is_person():
        info = NaturalPerson.objects.filter(person_id=request.user)
        userinfo = info.values()[0]

        useroj = NaturalPerson.objects.get(person_id=request.user)

        former_wallpaper = utils.get_user_wallpaper(me)

        # print(json.loads(request.body.decode("utf-8")))
        if request.method == "POST" and request.POST:

            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(request)
            attr_check_list = [attr for attr in attr_dict.keys() if attr not in [
                'gender', 'ava', 'wallpaper', 'accept_promote', 'wechat_receive_level']]
            if html_display['warn_code'] == 1:
                return render(request, "person_account_setting.html", locals())

            modify_info = []
            if attr_dict['gender'] != useroj.get_gender_display():
                modify_info.append(
                    f'gender: {useroj.get_gender_display()}->{attr_dict["gender"]}')
            if attr_dict['accept_promote'] != useroj.get_accept_promote_display():
                modify_info.append(
                    f'accept_promote: {useroj.get_accept_promote_display()}->{attr_dict["accept_promote"]}')
            if attr_dict['wechat_receive_level'] != useroj.get_wechat_receive_level_display():
                modify_info.append(
                    f'wechat_receive_level: {useroj.get_wechat_receive_level_display()}->{attr_dict["wechat_receive_level"]}')
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
                useroj.gender = NaturalPerson.Gender.MALE if attr_dict[
                    'gender'] == '男' else NaturalPerson.Gender.FEMALE
            if attr_dict['wechat_receive_level'] != useroj.wechat_receive_level:
                useroj.wechat_receive_level = NaturalPerson.ReceiveLevel.MORE if attr_dict[
                    'wechat_receive_level'] == '接受全部消息' else NaturalPerson.ReceiveLevel.LESS
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
        former_wallpaper = utils.get_user_wallpaper(me)
        org_tags = list(useroj.tags.all())
        all_tags = list(OrganizationTag.objects.all())
        if request.method == "POST" and request.POST:

            ava = request.FILES.get("avatar")
            wallpaper = request.FILES.get("wallpaper")
            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(request)
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
                modify_info += [
                    f'{attr}: {getattr(useroj, attr)}->{attr_dict[attr]}']
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
                            useroj.tags.add(
                                OrganizationTag.objects.get(name=tag_name))
                        else:
                            useroj.tags.remove(
                                OrganizationTag.objects.get(name=tag_name))
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


def _create_freshman_account(sid: str, email: str = None):
    """创建用户和自然人，检查并修改新生创建状态，原子化操作"""
    try:
        with transaction.atomic():
            current = "获取新生信息"
            freshman: Freshman = Freshman.objects.select_for_update().get(sid=sid)
            name = freshman.name
            np_gender = (NaturalPerson.Gender.MALE
                         if freshman.gender == "男" else
                         NaturalPerson.Gender.FEMALE)
            current = "确认注册状态"
            assert freshman.status != Freshman.Status.REGISTERED
            if email is None:
                domain = "pku.edu.cn" if freshman.grade[2:].startswith(
                    "1") else "stu.pku.edu.cn"
                email = f"{sid}@{domain}"
            current = "随机生成密码"
            password = GLOBAL_CONFIG.hasher.encode(name + str(random.random()))
            current = "创建用户"
            user = User.objects.create_user(
                username=sid, name=name,
                usertype=UTYPE_PER,
                password=password
            )
            current = "创建个人账号"
            NaturalPerson.objects.create(
                person_id=user,
                stu_id_dbonly=sid,
                name=name,
                gender=np_gender,
                stu_major="元培计划（待定）",
                stu_grade=freshman.grade,
                email=email,
            )
            current = "更新注册状态"
            freshman.status = Freshman.Status.REGISTERED
            freshman.save()
        return
    except:
        return current


@logger.secure_view()
def freshman(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect(message_url(wrong('你已经登录，无需进行注册!')))

    if request.GET.get("success") is not None:
        alert = request.GET.get("alert")
        return render(request, "registerSuccess.html", dict(alert=alert))

    # 选择生源地列表，前端使用量
    address_set = set(Freshman.objects.all().values_list("place", flat=True))
    address_set.discard("")
    address_set.discard("其它")
    address_list = sorted(address_set)
    address_list.append("其它")
    html_path = "freshman-top.html"
    # 准备创建用的变量
    need_create = False
    if request.method == "POST":
        # 这些也是失败时的前端使用量
        try:
            sid = request.POST["sid"]
            sname = request.POST["sname"]
            gender = request.POST["gender"]
            send_to = request.POST.get("type", "")
            check_more = not send_to
            if check_more:
                birthday = request.POST["birthday"]  # 前端使用
                birthplace = request.POST["birthplace"]
                email = request.POST["email"]
        except:
            err_msg = "提交信息不足"
            return render(request, html_path, locals())
        try:
            sid = str(sid)
            sname = str(sname)
            gender = str(gender)
            if check_more:
                birthday_date = datetime.strptime(birthday, "%Y-%m-%d").date()
                birthplace = str(birthplace)
                email = str(email)
        except:
            err_msg = "错误的个人信息格式"
            return render(request, html_path, locals())
        try:
            freshman: Freshman = Freshman.objects.get(sid=sid)
        except:
            err_msg = "暂不存在该学号的新生信息"
            return render(request, html_path, locals())
        try:
            assert freshman.name == sname, "姓名不匹配"
            assert freshman.gender == gender, "个人信息错误"
            if check_more:
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
        if check_more:
            need_create = True
        elif send_to == "wechat":
            from extern.wechat import send_wechat
            auth = GLOBAL_CONFIG.hasher.encode(sid + "_freshman_register")
            send_wechat(
                [sid], "新生注册邀请", "点击按钮即可注册账号",
                url=f"/freshman/?sid={sid}&auth={auth}"
            )
            err_msg = "已向企业微信发送注册邀请，点击邀请信息即可注册！"
            return render(request, html_path, locals())

    if request.GET.get("sid") is not None and request.GET.get("auth") is not None:
        sid = request.GET["sid"]
        auth = request.GET["auth"]
        if auth != GLOBAL_CONFIG.hasher.encode(sid + "_freshman_register"):
            err_msg = "密钥错误，验证失败"
            return render(request, html_path, locals())
        need_create = True

    if need_create:
        try:
            email = email
        except:
            email = None
        try:
            freshman: Freshman = Freshman.objects.get(sid=sid)
        except:
            err_msg = "暂不存在该学号的新生信息"
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

        current = _create_freshman_account(sid, email=email)
        if current is not None:
            err_msg = f"在{current}时意外发生了错误，请联系管理员"
            return render(request, html_path, locals())

        # 发送企业微信邀请，不会报错
        invite_to_wechat(sid, multithread=True)

        err_msg = "您的账号已成功注册，请尽快加入企业微信以接受后续通知！"
        return redirect("/freshman/?success=1&alert=" + err_msg)

    return render(request, html_path, locals())


@login_required(redirect_field_name="origin")
@logger.secure_view()
def userAgreement(request: UserRequest):
    # 不要加check_user_access，因为本页面就是该包装器首次登录时的跳转页面之一
    if not request.user.is_valid():
        return redirect("/index/")

    if request.method == "POST":
        confirm = request.POST.get('confirm') == 'yes'
        if not confirm:
            return redirect('/logout/')
        request.session['confirmed'] = 'yes'
        return redirect('/modpw/')

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "用户须知")
    return render(request, 'user_agreement.html',
                  dict(request=request, bar_display=bar_display))


@logger.secure_view()
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
                    user = User.objects.create_user(
                        username=sno, name=name,
                        usertype=UTYPE_PER,
                        password=password
                    )
                except:
                    # 存在用户
                    return HttpResponseRedirect("/admin/")

                try:
                    new_user = NaturalPerson.objects.create(
                        person_id=user,
                        stu_id_dbonly=sno,
                        name=name,
                        email=email,
                        stu_grade=stu_grade,
                        gender=NaturalPerson.Gender.MALE if gender == '男'
                        else NaturalPerson.Gender.FEMALE,
                    )
                except:
                    # 创建失败，把创建的用户删掉
                    return HttpResponseRedirect("/admin/")
                return HttpResponseRedirect("/index/")
        return render(request, "auth_register_boxed.html")
    else:
        return HttpResponseRedirect("/index/")


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
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

    html_display = {}

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
                    id__in=Position.objects.activated().filter(
                        is_admin=True, org=org).values("person")
                ),  # TODO:直接查到一个NaturalPerson的Query_set
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
        Q(title__icontains=query) | Q(organization_id__oname__icontains=query) & ~Q(
            status=Activity.Status.CANCELED)
        & ~Q(status=Activity.Status.REJECT)
        & ~Q(status=Activity.Status.REVIEWING) & ~Q(status=Activity.Status.ABORT)
    )

    # 活动要呈现的内容
    activity_field = ["活动名称", "承办小组", "状态"]

    #先赋空值保证search.html正常运行
    feedback_field, feedback_list = [], []
    # feedback_field = ["标题", "状态", "负责小组", "内容"]
    # feedback_list = Feedback.objects.filter(
    #     Q(public_status=Feedback.PublicStatus.PUBLIC)
    # ).filter(
    #     Q(title__icontains=query)
    #     | Q(org__oname__icontains=query)
    # )

    # 学术地图内容
    academic_map_dict = get_search_results(query)
    academic_list = []
    for username, contents in academic_map_dict.items():
        info = dict()
        np = NaturalPerson.objects.get(person_id__username=username)
        info['ref'] = np.get_absolute_url() + '#tab=academic_map'
        info['avatar'] = np.get_user_ava()
        info['sname'] = np.name
        academic_list.append((info, contents))

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "信息搜索")
    return render(request, "search.html", locals())


@logger.secure_view()
@utils.record_attack(Exception, as_attack=True)
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
                        "secret": CONFIG.email.hasher.encode(msg),  # content加密后的密文
                    }
                    post_data = json.dumps(post_data)
                    pre, suf = email.rsplit("@", 1)
                    if len(pre) > 5:
                        pre = pre[:2] + "*" * len(pre[2:-3]) + pre[-3:]
                    try:
                        response = requests.post(
                            CONFIG.email.url, post_data, timeout=6)
                        response = response.json()
                        if response["status"] != 200:
                            display = wrong(f"未能向{pre}@{suf}发送邮件")
                            print("向邮箱api发送失败，原因：", response["data"]["errMsg"])
                        else:
                            # 记录验证码发给谁 不使用username防止被修改
                            utils.set_captcha_session(
                                request, username, captcha)
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
                send_verify_code(username, captcha)
                display = succeed(f"验证码已发送至企业微信")
                display["noshow"] = True
                display["alert"] = True
                utils.set_captcha_session(request, username, captcha)
                display.setdefault("colddown", 60)
            else:
                captcha, expired, old = utils.get_captcha(
                    request, username, more_info=True)
                if not old:
                    display = wrong("请先发送验证码")
                elif expired:
                    display = wrong("验证码已过期，请重新发送")
                elif str(vertify_code).upper() == captcha.upper():
                    auth.login(request, user)
                    update_related_account_in_session(
                        request, user.username)
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
@logger.secure_view()
def modpw(request: UserRequest):
    """
        可能在三种情况进入这个页面：首次登陆；忘记密码；或者常规的修改密码。
        在忘记密码时，可以允许不输入旧的密码
        在首次登陆时，现在写的也可以不输入旧的密码（我还没想好这样合不合适）
            以上两种情况都可以直接进行密码修改
        常规修改要审核旧的密码
    """
    user = request.user
    isFirst = request.user.is_newuser
    # 在其他界面，如果isFirst为真，会跳转到这个页面
    # 现在，请使用@utils.check_user_access(redirect_url)包装器完成用户检查

    html_display = {}

    err_code = 0
    err_message = None
    forgetpw = request.session.get("forgetpw", "") == "yes"  # added by pht
    username = request.user.username

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
                    user.is_newuser = False
                    user.save()

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
    return render(request, "modpw.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def subscribeOrganization(request: UserRequest):
    html_display = {}
    if not request.user.is_person():
        succeed('小组账号不支持订阅，您可以在此查看小组列表！', html_display)
        html_display.update(readonly=True)

    me = get_person_or_org(request.user)
    # orgava_list = [(org, utils.get_user_ava(org, UTYPE_ORG)) for org in org_list]
    otype_infos = [(
        otype,
        list(Organization.objects.activated().filter(otype=otype)
             .select_related("organization_id")),
    ) for otype in OrganizationType.objects.all().order_by('-otype_id')]

    # 获取不订阅列表（数据库里的是不订阅列表）
    if request.user.is_person():
        unsubscribe_set = set(me.unsubscribe_list.values_list(
            'organization_id__username', flat=True))
    else:
        unsubscribe_set = set(Organization.objects.values_list(
            'organization_id__username', flat=True))

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    # 小组暂且不使用订阅提示
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name='我的订阅' if request.user.is_person() else '小组一览')

    # all_number = NaturalPerson.objects.activated().all().count()    # 人数全体 优化查询
    return render(request, "organization_subscribe.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def saveSubscribeStatus(request: UserRequest):
    if not request.user.is_person():
        return JsonResponse({"success": False})

    me = get_person_or_org(request.user)
    params = json.loads(request.body.decode("utf-8"))

    with transaction.atomic():
        if "id" in params.keys():
            try:
                org = Organization.objects.get(
                    organization_id__username=params["id"])
            except:
                return JsonResponse({"success": False})
            if params["status"]:
                me.unsubscribe_list.remove(org)
            else:
                if not org.otype.allow_unsubscribe:  # 非法前端量修改
                    return JsonResponse({"success": False})
                me.unsubscribe_list.add(org)
        elif "otype" in params.keys():
            try:
                unsubscribed_list = me.unsubscribe_list.filter(
                    otype__otype_id=params["otype"]
                )
                org_list = Organization.objects.filter(
                    otype__otype_id=params["otype"])
            except:
                return JsonResponse({"success": False})
            if params["status"]:  # 表示要订阅
                for org in unsubscribed_list:
                    me.unsubscribe_list.remove(org)
            else:  # 不订阅
                try:
                    otype = OrganizationType.objects.get(
                        otype_id=params["otype"])
                except:
                    return JsonResponse({"success": False})
                if not otype.allow_unsubscribe:  # 非法前端量修改
                    return JsonResponse({"success": False})
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


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def notifications(request: HttpRequest):
    html_display = {}

    # 处理GET一键阅读或错误信息
    if request.method == "GET" and request.GET:
        get_name = request.GET.get("read_name", None)
        if get_name == "readall":
            notificaiton_set = Notification.objects.activated().filter(
                receiver=request.user,
                typename=Notification.Type.NEEDREAD,
                status=Notification.Status.UNDONE)
            count = notificaiton_set.count()
            notificaiton_set.update(
                status=Notification.Status.DONE, finish_time=datetime.now())
            succeed(f"成功将{count}条通知设为已读！", html_display)
        elif get_name == "deleteall":
            notificaiton_set = Notification.objects.activated().filter(
                receiver=request.user,
                typename=Notification.Type.NEEDREAD,
                status=Notification.Status.DONE)
            count = notificaiton_set.count()
            notificaiton_set.update(status=Notification.Status.DELETE)
            succeed(f"您已成功删除{count}条通知！", html_display)
        else:
            # 读取外部错误信息
            my_messages.transfer_message_context(request.GET, html_display)

    # 接下来处理POST相关的内容
    elif request.method == "POST":
        # 发生了通知处理的事件
        try:
            post_args = json.loads(request.body.decode("utf-8"))
            notification_id = int(post_args['id'])
            Notification.objects.activated().get(id=notification_id, receiver=request.user)
        except:
            wrong("请不要恶意发送post请求！！", html_display)
            return JsonResponse({"success": False})
        try:
            if "cancel" in post_args['function']:
                context = notification_status_change(
                    notification_id, Notification.Status.DELETE)
            else:
                context = notification_status_change(notification_id)
            my_messages.transfer_message_context(
                context, html_display, normalize=False)
        except:
            wrong("删除通知的过程出现错误！请联系管理员。", html_display)
        return JsonResponse({"success": my_messages.get_warning(html_display)[0] == SUCCEED})

    done_notifications = Notification.objects.activated().filter(
        receiver=request.user,
        status=Notification.Status.DONE).order_by("-finish_time")
    undone_notifications = Notification.objects.activated().filter(
        receiver=request.user,
        status=Notification.Status.UNDONE).order_by("-start_time")

    done_list = notification2Display(done_notifications)
    undone_list = notification2Display(undone_notifications)

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user,
                                               navbar_name="通知信箱")
    return render(request, "notifications.html", locals())

