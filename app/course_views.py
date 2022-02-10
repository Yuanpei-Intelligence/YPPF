from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Position,
    OrganizationType,
    Position,
    Activity,
    ActivityPhoto,
    Participant,
    Reimbursement,
)
from app.course_utils import (
    ActivityException,
    create_single_course_activity,
    modify_course_activity,
)
from app.comment_utils import addComment, showComment
from app.utils import (
    get_person_or_org,
    escape_for_templates,
)

import io
import csv
import os
import qrcode

import urllib.parse
from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Q, F

__all__ = [
    'editCourseActivity', 
    'addSingleCourseActivity',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[editCourseActivity]', record_user=True)
def editCourseActivity(request, aid):
    """
    编辑单次书院课程活动，addActivity的简化版
    """
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type) # 这里的me应该为小组账户
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        if user_type == "Person":
            html_display=utils.user_login_org(request,activity.organization_id)
            if html_display['warn_code']==1:
                return redirect(message_url(wrong(html_display["warn_message"])))
            else: # 成功以小组账号登陆
                # 防止后边有使用，因此需要赋值
                user_type = "Organization"
                request.user = activity.organization_id.organization_id #小组对应user
                me = activity.organization_id #小组
        if activity.organization_id != me:
            return redirect(message_url(wrong("无法修改其他课程小组的活动!")))

        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    if request.method == "POST" and request.POST:
        # 仅这几个阶段可以修改？
        if (
                activity.status != Activity.Status.REVIEWING and
                activity.status != Activity.Status.APPLYING and
                activity.status != Activity.Status.WAITING
        ):
            return redirect(message_url(wrong('当前活动状态不允许修改!'),
                                        f'/viewActivity/{activity.id}'))
        
        try:
            # 只能修改自己的活动
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(id=aid)
                org = get_person_or_org(request.user, "Organization")
                assert activity.organization_id == org
                modify_course_activity(request, activity)
            html_display["warn_msg"] = "修改成功。"
            html_display["warn_code"] = 2
        except ActivityException as e:
            html_display["warn_msg"] = str(e)
            html_display["warn_code"] = 1
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT

    # 下面的操作基本如无特殊说明，都是准备前端使用量
    defaultpics = [{"src": f"/static/assets/img/announcepics/{i+1}.JPG", "id": f"picture{i+1}"} for i in range(5)]
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava() 
    try:
        org = get_person_or_org(request.user, "Organization")
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 下面是前端展示的变量，均可编辑
    title = utils.escape_for_templates(activity.title)
    location = utils.escape_for_templates(activity.location)
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
    # introduction = escape_for_templates(activity.introduction) # 暂定不需要简介
    
    examine_teacher = activity.examine_teacher.name
    status = activity.status
    available_teachers = NaturalPerson.objects.filter(identity=NaturalPerson.Identity.TEACHER)

    edit = True # 前端据此区分是编辑还是创建
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    
    bar_display = utils.get_sidebar_and_navbar(request.user, "修改单次课程活动")

    return render(request, "lesson_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[addSingleCourseActivity]', record_user=True)
def addSingleCourseActivity(request):
    """
    创建单次书院课程活动，addActivity的简化版
    """
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type) # 这里的me应该为小组账户
        if user_type != "Organization":
            return redirect(message_url(wrong('书院课程小组账号才能开设课程活动!')))
        if me.oname == YQP_ONAME:
            return redirect("/showActivity") # TODO: 可以重定向到书院课程聚合页面
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    if request.method == "POST" and request.POST:
        try:
            with transaction.atomic():
                aid, created = create_single_course_activity(request)
                if not created:
                    return redirect(message_url(
                        succeed('存在信息相同的课程活动，已为您自动跳转!'),
                        f'/viewActivity/{aid}')) # 可以重定向到书院课程聚合页面
                return redirect(f"/editCourseActivity/{aid}")
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT
    
    # 前端使用量
    defaultpics = [{"src": f"/static/assets/img/announcepics/{i+1}.JPG", "id": f"picture{i+1}"} for i in range(5)]
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava() 
    
    available_teachers = NaturalPerson.objects.teachers()
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    bar_display = utils.get_sidebar_and_navbar(request.user, "发起单次课程活动")
    edit = False # 前端据此区分是编辑还是创建
    
    return render(request, "lesson_add.html", locals())
