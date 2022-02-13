from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Activity,
)
from app.course_utils import (
    create_single_course_activity,
    modify_course_activity,
    cancel_course_activity,
)
from app.utils import (
    get_person_or_org,
)

from datetime import datetime, timedelta
from django.db import transaction

__all__ = [
    'editCourseActivity', 
    'addSingleCourseActivity',
    'showCourseActivity',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[editCourseActivity]', record_user=True)
def editCourseActivity(request, aid):
    """
    编辑单次书院课程活动，addActivity的简化版
    """
    # 检查用户身份
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type)  # 这里的me应该为小组账户
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        if user_type == "Person":
            html_display = utils.user_login_org(
                request, activity.organization_id)
            if html_display['warn_code'] == 1:
                return redirect(message_url(wrong(html_display["warn_message"])))
            else:  # 成功以小组账号登陆
                # 防止后边有使用，因此需要赋值
                user_type = "Organization"
                request.user = activity.organization_id.organization_id  # 小组对应user
                me = activity.organization_id  # 小组
        if activity.organization_id != me:
            return redirect(message_url(wrong("无法修改其他课程小组的活动!")))
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 这个页面只能修改书院课程活动(category=1)
    if activity.category != Activity.ActivityCategory.COURSE:
        return redirect(message_url(wrong('当前活动不是书院课程活动!'),
                                    f'/viewActivity/{activity.id}'))
    # 课程活动无需报名，在开始前都是等待中的状态
    if activity.status != Activity.Status.WAITING:
        return redirect(message_url(wrong('当前活动状态不允许修改!'),
                                    f'/viewActivity/{activity.id}'))

    if request.method == "POST" and request.POST:
        # 修改活动
        try:
            # 只能修改自己的活动
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(id=aid)
                org = get_person_or_org(request.user, "Organization")
                assert activity.organization_id == org
                modify_course_activity(request, activity)
            html_display["warn_msg"] = "修改成功。"
            html_display["warn_code"] = 2
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT

    # 前端使用量
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava()
    bar_display = utils.get_sidebar_and_navbar(request.user, "修改单次课程活动")

    # 前端使用量，均可编辑
    title = utils.escape_for_templates(activity.title)
    location = utils.escape_for_templates(activity.location)
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
    # introduction = escape_for_templates(activity.introduction) # 暂定不需要简介
    edit = True  # 前端据此区分是编辑还是创建

    return render(request, "lesson_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[addSingleCourseActivity]', record_user=True)
def addSingleCourseActivity(request):
    """
    创建单次书院课程活动，addActivity的简化版
    """
    # 检查用户身份
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type)  # 这里的me应该为小组账户
        if user_type != "Organization" or me.otype.otype_name != COURSE_TYPENAME:
            return redirect(message_url(wrong('书院课程小组账号才能开设课程活动!')))
        if me.oname == YQP_ONAME:
            return redirect("/showActivity")  # TODO: 可以重定向到书院课程聚合页面
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    if request.method == "POST" and request.POST:
        # 创建活动
        try:
            with transaction.atomic():
                aid, created = create_single_course_activity(request)
                if not created:
                    return redirect(message_url(
                        succeed('存在信息相同的课程活动，已为您自动跳转!'),
                        f'/viewActivity/{aid}'))
                return redirect(f"/editCourseActivity/{aid}")
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT

    # 前端使用量
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava()
    bar_display = utils.get_sidebar_and_navbar(request.user, "发起单次课程活动")
    edit = False  # 前端据此区分是编辑还是创建

    return render(request, "lesson_add.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='course_views[showCourseActivity]', record_user=True)
def showCourseActivity(request):
    """
    筛选本学期已结束的课程活动、未开始的课程活动，在课程活动聚合页面进行显示。
    """

    # Sanity check and start a html_display.
    _, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user, user_type)  # 获取自身

    if user_type != "Organization" or me.otype.otype_name != COURSE_TYPENAME:
        return redirect(message_url(wrong('只有书院课程组织才能查看此页面!')))

    all_activity_list = (
        Activity.objects
        .activated()
        .filter(organization_id=me)
        .filter(category=Activity.ActivityCategory.COURSE)
        .order_by("-start")
    )

    future_activity_list = (
        all_activity_list.filter(
            status__in=[
                Activity.Status.REVIEWING,
                Activity.Status.APPLYING,
                Activity.Status.WAITING,
                Activity.Status.PROGRESSING,
            ]
        )
    )

    finished_activity_list = (
        all_activity_list
        .filter(
            status__in=[
                Activity.Status.END,
                Activity.Status.CANCELED,
            ]
        )
        .order_by("-end")
    )  # 本学期的已结束活动（包括已取消的）

    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="我的活动")

    # 取消单次活动
    if request.method == "POST" and request.POST:
        # 获取待取消的活动
        try:
            aid = int(request.POST.get("cancel-action"))
            activity = Activity.objects.get(id=aid)
        except:
            return redirect(message_url(wrong('遇到不可预料的错误。如有需要，请联系管理员解决!'), request.path))

        if activity.organization_id != me:
            return redirect(message_url(wrong('您没有取消该课程活动的权限!'), request.path))
        
        if activity.status in [
            Activity.Status.REJECT,
            Activity.Status.ABORT,
            Activity.Status.END,
            Activity.Status.CANCELED,
        ]:
            return redirect(message_url(wrong('该课程活动已结束，不可取消!'), request.path))

        assert activity.status not in [
            Activity.Status.REVIEWING,
            Activity.Status.APPLYING,
        ], "课程活动状态非法"  # 课程活动不应出现这两个状态

        # 取消活动
        with transaction.atomic():
            activity = Activity.objects.select_for_update().get(id=aid)
            error = cancel_course_activity(request, activity)
        
        # 无返回值表示取消成功，有则失败
        if error is None:
            html_display["warn_code"] = 2
            html_display["warn_message"] = "成功取消活动。"
        else:
            return redirect(message_url(wrong(error)), request.path)

    return render(request, "org_show_course_activity.html", locals())
