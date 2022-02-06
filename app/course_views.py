"""
course_views.py

选课页面: selectCourse
课程详情页面: viewCourse
"""
import json
from datetime import datetime, timedelta

from django.db import transaction

from app.course_utils import *
from app.course_utils import (course2Display, create_single_course_activity,
                              modify_course_activity, registrationStatusChange,
                              registrationStatusCreate)
from app.models import (Activity, Course, CourseParticipant, NaturalPerson,
                        Organization, OrganizationType, Position)
from app.utils import get_person_or_org
from app.views_dependency import *

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


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(record_user=True,
                     record_request_args=True,
                     source='views[selectCourse]')
def selectCourse(request):
    """
    学生选课的聚合页面，包括: 
    1. 所有开放课程的选课信息，分开显示已选和未选的课程
    2. 在预选和补退选阶段，学生可以通过点击课程对应的按钮实现选课或者退选，
    且点击后页面显示发生相应的变化。（可参考学校选课网）
    3. 显示选课结果（最好通过分页实现，不需要再新增url）
    
    用户权限: 组织账号不应该进入该页面；学生/老师账号可以进入，但是老师账号没有选课功能。
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_person = True if user_type == "Person" else False

    if not is_person:
        # 组织账号不应该进入这个页面
        redirect(message_url(wrong("非学生账号不能选课！")))

    me = NaturalPerson.objects.get(person_id=request.user)

    # TODO: task 10 ljy 2022-02-07
    # 和编写开课页面的同学对接，尽量在开课的同时完成状态创建，不要每次访问都检查一遍。

    if not me.is_staff:
        registration_status_create(me)  # 创建选课状态
        html_display["willing_point"] = remaining_willingness_point(me)
    else:
        html_display["is_staff"] = True

    # 学生选课或者取消选课

    if request.method == 'POST':

        # TODO: task 10 ljy 2022-02-07
        # 和前端对接，统一传递的参数内容

        # 需要的参数: 课程id，操作action: select/cancel（json格式）

        post_args = json.loads(request.body.decode("utf-8"))
        try:
            course_id = int(post_args["id"])
        except:
            html_display["warn_code"] = 1  # 失败
            html_display["warn_message"] = "请不要恶意发送post请求！"
            return JsonResponse({"success": False})
        try:
            func = post_args["action"]
            assert func == "select" or func == "cancel"
        except:
            html_display["warn_code"] = 1  # 失败
            html_display["warn_message"] = "请不要恶意发送post请求！！"
            return JsonResponse({"success": False})
        try:
            Course.objects.activated().get(id=course_id,
                                           participant_set__person=me)
        except:
            html_display["warn_code"] = 1  # 失败
            html_display["warn_message"] = "请不要恶意发送post请求！！"
            return JsonResponse({"success": False})
        try:
            # 对学生的选课状态进行变更
            context = registration_status_change(course_id, me, func)
            html_display["warn_code"] = context["warn_code"]
            html_display["warn_message"] = context["warn_message"]
            if context["warn_code"] == 1:
                return JsonResponse({"success": False})
            else:  # 成功更新选课状态
                return JsonResponse({"success": True})
        except:
            html_display["warn_code"] = 1  # 意外失败
            html_display["warn_message"] = "选课过程出现错误！请联系管理员。"
            return JsonResponse({"success": False})

    html_display["is_myself"] = True
    
    # 当前用户已选和未选的课，已选对应的状态有: SELECT和SUCCESS，未选对应的状态有UNSELECT和FAILED

    unselected_course = Course.objects.unselected(me)
    selected_course = Course.objects.selected(me)

    # 前端用于显示的内容: 两个list，list中每个元素是一个dict，包含课程的具体信息。
    # 两个list的顺序都和课程id一致。

    unselected_display = course2Display(unselected_course, me, detail=True)
    selected_display = course2Display(selected_course, me, detail=True)

    bar_display = utils.get_sidebar_and_navbar(request.user, "书院课程")

    # TODO: task 10 ljy 2022-02-07
    # 和前端对接: 
    # 1、点击课程名跳转到课程详情页（viewCourse对应的页面）
    # 2、根据选课阶段的不同，每门课对应的按钮要改变。例如某门课处于非选课阶段，
    # 那么它对应的按钮应该处于非活跃状态。
    # 3、（暂定）对于老师账号，可以进入该页面，但是不显示按钮。

    return HttpResponse()


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(record_user=True,
                     record_request_args=True,
                     source='views[courseDetail]')
def viewCourse(request):
    """
    展示一门课程的详细信息
    
    功能: 
    1、不区分用户类型，都呈现课程的详细信息。正常情况下，组织账号不会进入这里。
    2、可以直接返回到选课页面

    GET参数: ?courseid=<int>
    """

    valid, user_type, html_display = utils.check_user_type(request.user)

    course_id = int(request.GET.get("courseid", None))
    try:
        course = Course.objects.filter(id=course_id)
    except:
        context = {}
        context["warn_code"] = 1
        context["warn_message"] = f"课程{course_id}不存在"
        return EXCEPT_REDIRECT

    me = utils.get_person_or_org(request.user, user_type)
    course_display = course2Display(course, me, detail=True)

    # TODO: task 10 ljy 2022-02-07 
    # 和前端对接: 按返回按钮可以redirect到selectCourse页面

    return HttpResponse()
