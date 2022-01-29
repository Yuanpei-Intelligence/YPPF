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
from app.course_activity_utils import (
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
    'editCourseActivity', 'releaseCourseActivity', 
    'addSingleCourseActivity', 'cancelCourseActivity',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[editCourseActivity]', record_user=True)
def editCourseActivity(request, aid):
    """
    编辑单次书院课程活动，若该活动已发布，则同时通知所有选课学生
    ---------------
    基本完工

    
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
            return redirect(message_url(wrong("无法修改其他小组的活动!")))

        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 处理 POST 请求
    # 在这个界面，不会返回render，而是直接跳转到viewactivity，可以不设计bar_display
    if request.method == "POST" and request.POST:

        # 仅这几个阶段可以修改 # FIXME: ?
        if (
                activity.status != Activity.Status.REVIEWING and
                activity.status != Activity.Status.APPLYING and
                activity.status != Activity.Status.WAITING
        ):
            return redirect(message_url(wrong('当前活动状态不允许修改!'),
                                        f'/viewActivity/{activity.id}')) # FIXME: 跳转聚合页面

        # 处理 comment # FIXME: ??
        if request.POST.get("comment_submit"):
            # 创建活动只能在审核时添加评论
            assert not activity.valid
            context = addComment(request, activity, activity.examine_teacher.person_id)
            # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
            assert context["warn_code"] == 2, context["warn_message"]
            # 成功后重新加载界面
            html_display["warn_msg"] = "评论成功。"
            html_display["warn_code"] = 2
        else:
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

        # 没过审，可以编辑评论区
        if not activity.valid:
            commentable = True
            front_check = True
        commentable = False
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
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 决定状态的变量
    # full_editable/accepted/None ( 小组编辑活动：除审查老师外全可修改/部分可修改/全部不可改 )
    #        full_editable 为 true 时，accepted 也为 true
    # commentable ( 是否可以评论 )

    # 下面是前端展示的变量,FIXME: 注释了一些用不上的

    title = utils.escape_for_templates(activity.title)
    budget = activity.budget
    location = utils.escape_for_templates(activity.location)
    apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    # apply_end_for_js = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
    introduction = escape_for_templates(activity.introduction)
    url = utils.escape_for_templates(activity.URL)

    # endbefore = activity.endbefore
    # bidding = activity.bidding
    # amount = activity.YQPoint
    # signscheme = "先到先得"
    # if bidding:
    #     signscheme = "抽签模式"
    # capacity = activity.capacity
    # yq_source = "向学生收取"
    # if activity.source == Activity.YQPointSource.COLLEGE:
    #     yq_source = "向学院申请"
    # no_limit = False
    # if capacity == 10000:
    #     no_limit = True
    examine_teacher = activity.examine_teacher.name
    status = activity.status
    available_teachers = NaturalPerson.objects.filter(identity=NaturalPerson.Identity.TEACHER)
    need_checkin = activity.need_checkin
    inner = activity.inner
    apply_reason = utils.escape_for_templates(activity.apply_reason)
    
    comments = showComment(activity)
    photo = str(activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE).image)
    uploaded_photo = False
    if str(photo).startswith("activity"):
        uploaded_photo = True
        photo_path = photo
        photo = os.path.basename(photo)
    else:
        photo_id = "picture" + os.path.basename(photo).split(".")[0]


    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    
    bar_display = utils.get_sidebar_and_navbar(request.user, "修改单次课程活动")

    return render(request, "lesson_modify.html", locals())
    

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[notifyCourseActivity]', record_user=True)
def notifyCourseActivity(request, aid=None): # TODO：通知与发布
    pass

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[addSingleCourseActivity]', record_user=True)
def addSingleCourseActivity(request):
    """
    编辑单次书院课程活动，若该活动已发布，则同时通知所有选课学生
    ---------------
    基本完工
 
    """
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type) # 这里的me应该为小组账户
        if user_type != "Organization":
            return redirect(message_url(wrong('书院课程小组账号才能开设课程活动!')))
        if me.oname == YQP_ONAME:
            return redirect("/showActivity") # FIXME:!!返回书院课程聚合页面?
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 处理 POST 请求
    # 在这个界面，不会返回render，而是直接跳转到viewactivity，可以不设计bar_display
    if request.method == "POST" and request.POST:
        try:
            with transaction.atomic():
                aid, created = create_single_course_activity(request)
                if not created:
                    return redirect(message_url(
                        succeed('存在信息相同的课程活动，已为您自动跳转!'),
                        f'/viewCourseActivity/{aid}')) # FIXME:!!书院课程聚合页面
                return redirect(f"/editCourseActivity/{aid}") # FIXME:!!课程活动编辑页面
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT
    
    # 下面的操作基本如无特殊说明，都是准备前端使用量
    defaultpics = [{"src": f"/static/assets/img/announcepics/{i+1}.JPG", "id": f"picture{i+1}"} for i in range(5)]
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava() 
    
    available_teachers = NaturalPerson.objects.teachers()
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    bar_display = utils.get_sidebar_and_navbar(request.user, "发起单次课程活动")

    return render(request, "lesson_add.html", locals())
    
    
'''
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[cancelCourseActivity]', record_user=True)
def cancelCourseActivity(request, aid=None): # FIXME: 放到聚合页面里？
    """
    取消单次书院课程活动，若活动已发布，同时通知所有选课学生
    ---------------

    """
    try:
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        org = activity.organization_id
        me = utils.get_person_or_org(request.user, user_type)
        ownership = False
        if user_type == "Organization" and org == me:
            ownership = True
        examine = False
        if user_type == "Person" and activity.examine_teacher == me:
            examine = True
        if not (ownership or examine) and activity.status in [
                Activity.Status.REVIEWING,
                Activity.Status.ABORT,
                Activity.Status.REJECT,
            ]:
            return redirect(message_url(wrong('该活动暂不可见!')))
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    html_display = dict()
    inform_share, alert_message = utils.get_inform_share(me)

    if request.method == "POST" and request.POST:
        try:
            if activity.status in [ # FIXME: ?
                Activity.Status.REJECT,
                Activity.Status.ABORT,
                Activity.Status.END,
                Activity.Status.CANCELED,
            ]:
                return redirect(message_url(wrong('该活动已结束，不可取消!'), request.path))
            if not ownership:
                return redirect(message_url(wrong('您没有修改该活动的权限!'), request.path))
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(id=aid)
                cancel_activity(request, activity)
                html_display["warn_code"] = 2
                html_display["warn_message"] = "成功取消活动。"
        except ActivityException as e:
            html_display["warn_code"] = 1
            html_display["warn_message"] = str(e)
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT
'''