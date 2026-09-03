import json
import random
from datetime import datetime, timedelta
from typing import cast, List, Tuple

from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib import auth
from django.db import transaction
from django.db.models import Q, F, Sum, QuerySet
from django.contrib.auth.password_validation import CommonPasswordValidator, NumericPasswordValidator
from django.core.exceptions import ValidationError

from django.core.validators import validate_email
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from django.views.decorators.http import require_POST


from utils.config.cast import str_to_time
from utils.http.utils import safe_local_redirect_target
from utils.marker import deprecated
from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Freshman,
    Position,
    AcademicTag,
    AcademicEntry,
    AcademicTextEntry,
    Organization,
    OrganizationTag,
    OrganizationType,
    Activity,
    ActivityPhoto,
    Participation,
    Notification,
    Wishes,
    Course,
    CourseRecord,
    Semester,
    AcademicQA,
    HomepageImage,
)
from app.password_reset_forms import PasswordResetForm, PasswordResetRequestForm
from app.utils import (
    get_person_or_org,
    record_modify_with_session,
    update_related_account_in_session,
)
from extern.wechat import (
    invite_to_wechat,
)
from extern.password_reset import (
    queue_prepared_password_reset_email,
    queue_prepared_password_reset_wechat,
)
from app.notification_utils import (
    notification_status_change,
    notification2Display,
)
from app.org_utils import set_default_subscription
from app.YQPoint_utils import add_signin_point
from app.academic_utils import (
    get_search_results,
    comments2display,
    get_js_tag_list,
    get_text_list,
    have_entries,
    get_tag_status,
    get_text_status,
)

from achievement.utils import personal_achievements
from achievement.api import unlock_achievement, unlock_YQPoint_achievements
from boot.settings import MEDIA_URL
from semester.api import current_semester



@csrf_protect
@login_required(redirect_field_name="origin")
@require_POST
@logger.secure_view()
def shiftAccount(request: HttpRequest):
    """Switch the current person session to an authorized related account."""

    username = request.session.get("NP")
    if not username:
        return redirect(message_url(wrong('没有可切换的账户信息，请重新登录!')))

    oname = request.POST.get("oname", "")

    # 不一定更新成功，但无所谓
    update_related_account_in_session(
        request, username, shift=True, oname=oname)

    origin = safe_local_redirect_target(
        request, request.POST.get("origin"), "/welcome/"
    )
    return redirect(origin)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def stuinfo(request: UserRequest):
    """
        进入到这里的逻辑:
        首先必须登录，并且不是超级账户
        如果name是空
            如果是个人账户，那么就自动跳转个人主页"/stuinfo/?name=myname&id=userid"
            如果是小组账户，那么自动跳转welcome
        如果name和id均非空
            利用id进行进行查找，不存在则跳转welcome
            如果存在，那么验证姓名是否匹配，不匹配则跳转welcome
            匹配则跳转个人主页"/stuinfo/?name=myname&id=userid"
        如果name非空但id为空
            如果不重名
                如果是自己，那么呈现并且有左边栏
                如果不是自己或者自己是小组，那么呈现并且没有侧边栏
            如果重名
                如果是自己，那么呈现并且有左边栏，并且补全id参数
                如果不是自己，那么跳转搜索"/search?Query=name"
    """

    html_display = {}

    oneself = get_person_or_org(request.user)

    name = request.GET.get('name', None)
    user_id = request.GET.get('id', None)
    
    if name is None:
        if request.user.is_org():
            return redirect("/orginfo/")  # 小组只能指定学生姓名访问
        else:  # 跳轉到自己的頁面
            assert request.user.is_person()
            return redirect(append_query(oneself.get_absolute_url(), **request.GET.dict()))
    else:
        # 双参数格式url处理
        if user_id is not None:
            # 如果有id参数，直接通过id查找用户
            try:
                user_id = int(user_id)
                get_user = User.objects.get(id=user_id)
                person = NaturalPerson.objects.get_by_user(get_user)
                # 验证姓名是否匹配
                if person.name != name:
                    return redirect(message_url(wrong('用户信息不匹配!')))
            except (ValueError, User.DoesNotExist, NaturalPerson.DoesNotExist):
                return redirect(message_url(wrong('用户不存在!')))
        # 若id不存在
        else:
            person = NaturalPerson.objects.filter(name=name)
            if len(person) == 0:  # 查无此人
                return redirect(message_url(wrong('用户不存在!')))
            if len(person) == 1:  # 无重名
                person = person[0]
            else:  # 存在重名
                # 如果自己是重名用户之一，那么跳转主页
                if request.user.is_person() and oneself.name == name:
                    person = cast(NaturalPerson, oneself)
                else:  # 不是自己，信息不全跳转搜索
                    return redirect("/search?Query=" + name)

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


        # 准备前端展示量，前移代码位置以保证后续功能不再使用locals()
        render_context = locals().copy()
        render_context.pop("is_myself", None)
        html_display["is_myself"] = is_myself

        render_context.update(
            html_display=html_display,
            inform_share=inform_share,
            alert_message=alert_message,
        )
        # ----------------------------------- 活动卡片 ----------------------------------- #

        # ------------------ 学时查询 ------------------ #

        # 只有是自己的主页时才显示学时
        if is_myself:
            past_courses = CourseRecord.objects.filter(person=oneself)

            # 无效学时，在前端呈现
            useless_courses = (
                past_courses
                .filter(invalid=True)
            )

            # 特判，需要一定时长才能计入总学时
            past_courses = (
                past_courses
                .exclude(invalid=True)
            )

            past_courses = past_courses.order_by('year', 'semester')
            useless_courses = useless_courses.order_by('year', 'semester')

            progress_list = []

            # 计算每个类别的学时
            for course_type in list(Course.CourseType):  # CourseType.values亦可
                progress_list.append((
                    past_courses
                    .filter(course__type=course_type)
                    .aggregate(Sum('total_hours'))
                )['total_hours__sum'] or 0)

            # 计算没有对应Course的学时
            progress_list.append((
                past_courses
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
            complete_hours = sum(progress_list)
            # 用于算百分比的实际总学时（考虑到可能会超学时），仅后端使用
            actual_total_hours = max(complete_hours, ruled_hours)
            if actual_total_hours > 0:
                progress_list = [
                    hour / actual_total_hours * 100 for hour in progress_list
                ]

            course_context = dict(
                ruled_hours=ruled_hours,
                complete_hours=complete_hours,
                past_courses=past_courses,
                useless_courses=useless_courses,
                progress_list=progress_list,
            )
            render_context.update(Course=course_context)

        # ------------------ 活动参与 ------------------ #

        participants = Participation.objects.activated().filter(SQ.sq(
                Participation.person, person))
        activities = Activity.objects.activated().filter(
            # ~Q(status=Activity.Status.CANCELED), # 暂时可以呈现已取消的活动
            id__in=SQ.qsvlist(participants, Participation.activity),
        )
        if request.user.is_person():
            # 因为上面筛选过活动，这里就不用筛选了
            # 之前那个写法是O(nm)的
            activities_me = Participation.objects.activated().filter(SQ.sq(
                Participation.person, oneself))
            activities_me = set(SQ.qsvlist(activities_me, Participation.activity))
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
                # ~Q(status=Activity.Status.CANCELED), # 暂时可以呈现已取消的活动
                id__in=SQ.qsvlist(participants, Participation.activity),
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
            chat_qa = progressing_chat.first()
            comment_display = comments2display(chat_qa.chat, request.user)
            # TODO: 字典的key有冲突风险
            html_display.update(comment_display)
            html_display["have_progressing_chat"] = True
        else:  # 没有进行中的问答，显示提问区
            html_display["have_progressing_chat"] = False
            html_display["accept_chat"] = person.get_user().accept_chat
            html_display["accept_anonymous"] = person.get_user().accept_anonymous_chat

        # ------------------ 查看学术地图 ------------------ #
        status_in = [AcademicEntry.EntryStatus.PUBLIC]
        is_teacher = request.user.is_person() and oneself.is_teacher()
        if is_myself:
            status_in = None
        elif is_teacher:
            status_in.append(AcademicEntry.EntryStatus.WAIT_AUDIT)

        # 判断用户是否有可以展示的内容
        content_status = status_in
        if is_myself:
            content_status = [AcademicEntry.EntryStatus.PUBLIC,
                              AcademicEntry.EntryStatus.WAIT_AUDIT]
        academic_params = dict()
        academic_params.update(
            is_inspector=is_teacher,
            author_id=person.person_id.id,
            have_content=have_entries(person, content_status),
            have_unaudit=have_entries(person, [AcademicEntry.EntryStatus.WAIT_AUDIT]),
        )

        # 获取用户已有的专业/项目的列表，用于select的默认选中项
        selected_dict = dict(
            selected_major_list=AcademicTag.Type.MAJOR,
            selected_minor_list=AcademicTag.Type.MINOR,
            selected_double_degree_list=AcademicTag.Type.DOUBLE_DEGREE,
            selected_project_list=AcademicTag.Type.PROJECT,
        )
        academic_params.update({
            name: get_js_tag_list(person, type, selected=True, status_in=status_in)
            for name, type in selected_dict.items()
        })

        # 获取用户已有的TextEntry的contents，用于TextEntry填写栏的前端预填写
        text_dict = dict(
            scientific_research_list=AcademicTextEntry.Type.SCIENTIFIC_RESEARCH,
            challenge_cup_list=AcademicTextEntry.Type.CHALLENGE_CUP,
            internship_list=AcademicTextEntry.Type.INTERNSHIP,
            scientific_direction_list=AcademicTextEntry.Type.SCIENTIFIC_DIRECTION,
            graduation_list=AcademicTextEntry.Type.GRADUATION,
        )
        academic_params.update({
            name: get_text_list(person, type, status_in)
            for name, type in text_dict.items()
        })

        # 最后获取每一种atype对应的entry的公开状态，如果没有则默认为公开
        tag_status_dict = dict(
            major_status=AcademicTag.Type.MAJOR,
            minor_status=AcademicTag.Type.MINOR,
            double_degree_status=AcademicTag.Type.DOUBLE_DEGREE,
            project_status=AcademicTag.Type.PROJECT,
        )
        academic_params.update({
            name: get_tag_status(person, type)
            for name, type in tag_status_dict.items()
        })
        text_status_dict = dict(
            scientific_research_status=AcademicTextEntry.Type.SCIENTIFIC_RESEARCH,
            challenge_cup_status=AcademicTextEntry.Type.CHALLENGE_CUP,
            internship_status=AcademicTextEntry.Type.INTERNSHIP,
            scientific_direction_status=AcademicTextEntry.Type.SCIENTIFIC_DIRECTION,
            graduation_status=AcademicTextEntry.Type.GRADUATION,
        )
        academic_params.update({
            name: get_text_status(person, type)
            for name, type in text_status_dict.items()
        })
        render_context.update(Academic=academic_params)

        # ------------------ 成就卡片 ------------------ #
        _, _, achievement_by_types = personal_achievements(person.get_user())
        achievement_params = dict(type_order_displays=achievement_by_types)
        render_context.update(Achievement=achievement_params)

        # ------------------ 前端准备 ------------------ #
        # 存储被查询人的信息
        _title = "我" if is_myself else (
            {0: "他", 1: "她"}.get(person.gender, 'Ta') if person.show_gender else "Ta")
        context = dict(
            person=person,
            title=_title,
            avatar_path=person.get_user_ava(),
            wallpaper_path=utils.get_user_wallpaper(person)
        )

        # 新版侧边栏, 顶栏等的呈现，采用 bar_display
        bar_display = utils.get_sidebar_and_navbar(
            request.user, navbar_name="个人主页", title_name=person.name
        )

        # post的url构造函数，避免&的转义
        post_url = person.get_absolute_url()
        render_context.update(bar_display=bar_display,
                              context=context, post_url=post_url)

        if request.session.get('alert_message'):
            render_context.update(load_alert_message=request.session.pop('alert_message'))

        # 浏览次数，必须在render之前
        # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
        NaturalPerson.objects.filter(id=person.id).update(
            visit_times=F('visit_times')+1)
        
        render_context.update(user=request.user)
        return render(request, "stuinfo.html", render_context)


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
        me = NaturalPerson.objects.get_by_user(request.user, activate=True)
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


@ensure_csrf_cookie
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
    inform_share, alert_message = utils.get_inform_share(
        me, is_myself=is_myself)

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
    continuing_activities = (
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

    ended_activities = (
        Activity.objects.activated()
        .filter(organization_id=org)
        .filter(status__in=[Activity.Status.CANCELED, Activity.Status.END])
        .order_by("-start")
    )

    # 筛选历史活动，具体为不是这个学期的活动
    history_activities = (
        Activity.objects.activated(noncurrent=True)
        .filter(organization_id=org)
        .order_by("-start")
    )

    # 如果是用户登陆的话，就记录一下用户有没有加入该活动，用字典存每个活动的状态，再把字典存在列表里

    def _display_activities(activities: QuerySet[Activity]) -> list[dict]:
        displays = []
        for act in activities:
            dictmp = {}
            dictmp["act"] = act
            hours = Activity.EndBeforeHours.prepare_times[act.endbefore]
            dictmp["endbefore"] = act.start - timedelta(hours=hours)
            if request.user.is_person():
                participation = Participation.objects.filter(
                    SQ.sq(Participation.activity, act), SQ.sq(Participation.person, me),
                ).first()
                dictmp["status"] = participation.status if participation else "无记录"
            displays.append(dictmp)
        return displays

    continuing_activity_list_participantrec = _display_activities(continuing_activities)
    ended_activity_list_participantrec = _display_activities(ended_activities)
    history_activity_list_participantrec = _display_activities(history_activities)

    # 判断我是不是老大, 首先设置为false, 然后如果有id和user一样, 就为True
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
        _unsubscribe_names = me.unsubscribe_list.values_list(
            "oname", flat=True)
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
            np = NaturalPerson.objects.get_by_user(request.user, update=True)
            if np.last_time_login is None or np.last_time_login.date() != nowtime.date():
                np.last_time_login = nowtime
                np.save()
                add_point, html_display['signin_display'] = add_signin_point(
                    request.user)
                html_display['first_signin'] = True  # 前端显示

    # 解锁成就-注册智慧书院
    # 如果放在注册页面结束判定 则已经注册好的用户获取不到该成就
    unlock_achievement(request.user, '注册智慧书院')

    # 元气满满系列更新
    semester = current_semester()
    start_datetime = datetime.combine(semester.start_date, datetime.min.time())
    end_datetime = datetime.combine(semester.end_date, datetime.max.time())
    unlock_YQPoint_achievements(request.user, start_datetime, end_datetime)

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
    # if request.method == "POST" and request.POST:
    #     wishtext = request.POST.get("wish")
    #     background = ""
    #     if request.POST.get("backgroundcolor") is not None:
    #         bg = request.POST["backgroundcolor"]
    #         try:
    #             assert len(bg) == 7 and bg[0] == "#"
    #             int(bg[1:], base=16)
    #             background = bg
    #         except:
    #             print(f"心愿背景颜色{bg}不合规")
    #     new_wish = Wishes.objects.create(text=wishtext, background=background)
    #     new_wish.save()

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

    homepage_image: List[Tuple[str, str]] = [
        (MEDIA_URL + filename, url) for (filename, url) in
            HomepageImage.objects.activated().order_by('sort_id')
            .values_list('image', 'redirect_url')
    ]

    """ 
        取出过去一周的所有活动，filter出上传了照片的活动，从每个活动的照片中随机选择一张
        如果列表为空，那么添加一张default，否则什么都不加。
    """
    all_photo_display = ActivityPhoto.objects.filter(
        type=ActivityPhoto.PhotoType.SUMMARY).order_by('-time')
    photo_display, _aid_set = list(), set()  # 实例的哈希值未定义，不可靠
    count = 9 - len(homepage_image)  # 算第一张导航图
    for photo in all_photo_display:
        # 不用activity，因为外键需要访问数据库
        if photo.activity_id not in _aid_set and photo.image:
            # 数据库设成了image可以为空而不是空字符串，str的判断对None没有意义

            photo.image = MEDIA_URL + str(photo.image)
            photo_display.append(photo)
            _aid_set.add(photo.activity_id)
            count -= 1

            if count <= 0:  # 目前至少能显示一个，应该也合理吧
                break
    photo_display = ()
    if photo_display:
        homepage_image = homepage_image[1:]   # 第一张只是封面图，如果有需要呈现的内容就不显示

    # 如果到这里，homepage_image 里面还是一张图片都没有，则采用硬编码的 fallback
    if len(homepage_image) == 0:
        homepage_image.append(('/static/assets/img/homepage_fallback.jpeg', ''))

    # -----------------------------天气---------------------------------
    # TODO: Put get_weather somewhere else
    from app.jobs import get_weather
    _weather = get_weather()
    if _weather.get('modify_time') is None:
        update_time_delta = timedelta(0)
    else:
        update_time_delta = datetime.now() - datetime.strptime(
            _weather['modify_time'], '%Y-%m-%d %H:%M:%S.%f')
    html_display['weather'] = _weather
    # 根据更新时间长短，展示不同的更新天气时间状态


    def days_hours_minutes_seconds(td):
        return td.days, td.seconds // 3600, (td.seconds // 60) % 60, td.seconds % 60
    days, hours, minutes, seconds = days_hours_minutes_seconds(
        update_time_delta)
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
        useroj = NaturalPerson.objects.get_by_user(request.user)
        userinfo = NaturalPerson.objects.filter(pk=useroj.pk).values()[0]

        former_wallpaper = utils.get_user_wallpaper(me)

        # print(json.loads(request.body.decode("utf-8")))
        if request.method == "POST" and request.POST:

            # 合法性检查
            attr_dict, show_dict, html_display = utils.check_account_setting(
                request)
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
                # 解锁成就-更新一次个人档案
                unlock_achievement(request.user, '更新一次个人档案')
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
            attr_dict, show_dict, html_display = utils.check_account_setting(
                request)
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
                usertype=User.Type.STUDENT,
                password=password
            )
            current = "创建个人账号"
            person = NaturalPerson.objects.create(
                user,
                stu_id_dbonly=sid,
                name=name,
                gender=np_gender,
                stu_major="元培计划（待定）",
                stu_grade=freshman.grade,
                email=email,
            )
            # 新账号默认只订阅学院机构与已加入小组，而非全部组织
            set_default_subscription(person)
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
    # 只查找公开的小组
    organization_qs = Organization.objects.activated()
    organization_list = organization_qs.filter(
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

    # 先赋空值保证search.html正常运行
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
        np: NaturalPerson = SQ.mget(NaturalPerson.person_id, username=username)
        info = dict(
            ref=np.get_absolute_url() + '#tab=academic_map',
            sname=np.name,
            avatar=np.get_user_ava(),
        )
        academic_list.append((info, contents))

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user, "信息搜索")
    return render(request, "search.html", locals())


@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST"])
@logger.secure_view()
@utils.record_attack(Exception, as_attack=True)
def forgetPassword(request: HttpRequest):
    """Request or consume a password-reset token without logging in."""
    if request.user.is_authenticated:
        return redirect("/welcome/")

    display = {}
    username = ""
    token = ""
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action in ("email", "wechat"):
            request_form = PasswordResetRequestForm(request.POST)
            if request_form.is_valid():
                username = request_form.cleaned_data["username"]
                def prepare_delivery():
                    if not utils.check_password_reset_request_rate(
                        request, username
                    ):
                        return None
                    user = User.objects.filter(username=username).first()
                    person = None
                    if user is not None:
                        try:
                            person = NaturalPerson.objects.get_by_user(user)
                        except NaturalPerson.DoesNotExist:
                            pass
                    if person is not None:
                        if action == "email":
                            try:
                                validate_email(person.email)
                            except ValidationError:
                                return None
                            token = utils.create_password_reset_token(
                                request, user)
                            return person.name, person.email, token
                        elif action == "wechat":
                            token = utils.create_password_reset_token(
                                request, user)
                            return user.username, token
                    return None

                if action == "email":
                    queue_prepared_password_reset_email(prepare_delivery)
                else:
                    queue_prepared_password_reset_wechat(prepare_delivery)
            display = succeed(
                "若账号及联系方式有效，重置凭证将发送至已绑定渠道")
            display.update(alert=True, noshow=True, colddown=60)
        elif action == "reset":
            reset_form = PasswordResetForm(request.POST)
            username = request.POST.get("username", "")
            token = request.POST.get("token", "")
            if reset_form.is_valid():
                try:
                    reset_succeeded = utils.reset_password_from_token(
                        request,
                        reset_form.cleaned_data["username"],
                        reset_form.cleaned_data["token"],
                        reset_form.cleaned_data["new_password"],
                    )
                except ValidationError as error:
                    display = wrong(error.messages[0])
                else:
                    if reset_succeeded:
                        return redirect(
                            reverse("index") + "?modinfo=success")
                    display = wrong("重置凭证无效或已失效")
            else:
                error = next(iter(reset_form.errors.values()))[0]
                display = wrong(str(error))
        else:
            display = wrong("重置凭证无效或已失效")

    context = {
        "display": display,
        "username": username,
    }
    return render(request, "forget_password.html", context)


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/", is_modpw=True)
@require_http_methods(["GET", "POST"])
@logger.secure_view()
def modpw(request: UserRequest):
    """
        首次登录时重复输入新密码；常规修改必须验证原密码。
        忘记密码使用独立的 /forgetpw/ token 流程。
    """
    user = request.user
    isFirst = request.user.is_newuser
    # 在其他界面，如果isFirst为真，会跳转到这个页面
    # 现在，请使用@utils.check_user_access(redirect_url)包装器完成用户检查

    html_display = {}

    err_code = 0
    err_message = None
    username = request.user.username

    if request.method == "POST" and request.POST:
        oldpassword = request.POST["pw"]
        newpw = request.POST["new"]
        strict_check = True
        min_length = 8
        try:
            if oldpassword == newpw and strict_check and not isFirst:
                raise ValidationError(message="新密码不能与原密码相同")
            elif newpw == username and strict_check:
                raise ValidationError(message="新密码不能与学号相同")
            elif newpw != oldpassword and isFirst:
                raise ValidationError(message="两次输入的密码不匹配")
            elif len(newpw) < min_length:
                raise ValidationError(message=f"新密码不能短于{min_length}位")
            if strict_check:
                NumericPasswordValidator().validate(password=newpw)
                CommonPasswordValidator().validate(password=newpw)
        except ValidationError as e:
            err_code = 1
            err_message = e.message
        else:
            # 首次登录或原密码验证成功时可以修改。
            if isFirst:
                userauth = True
            else:
                userauth = auth.authenticate(
                    username=username, password=oldpassword
                )  # 验证旧密码是否正确
            if userauth:  # 可以修改
                try:  # modified by pht: if检查是错误的，不存在时get会报错
                    user.set_password(newpw)
                    user.is_newuser = False
                    user.save(update_fields=['password', 'is_newuser'])

                    # record_modify_with_session(request,
                    #     "首次修改密码" if isFirst else "修改密码")
                    urls = reverse("index") + "?modinfo=success"
                    return redirect(urls)
                except Exception:
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
    # 获取所有组织类型
    organization_types = list(OrganizationType.objects.all().order_by('-otype_id'))

    # 强制只执行一次查询，prefetch防止多次查询
    organizations = list(Organization.objects.activated().select_related('otype').prefetch_related('organization_id'))

    # 获取组织信息
    otype_infos_dict = {otype: [] for otype in organization_types}
    for org in organizations:
        otype_infos_dict[org.otype].append(org)
    otype_infos = [(otype, otype_infos_dict[otype]) for otype in organization_types]


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

    notes_list = notification2Display(
        done_notifications) + notification2Display(undone_notifications)

    # 新版侧边栏, 顶栏等的呈现，采用 bar_display, 必须放在render前最后一步
    bar_display = utils.get_sidebar_and_navbar(request.user,
                                               navbar_name="通知信箱")
    return render(request, "notifications.html", locals())
