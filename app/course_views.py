from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Activity,
    Position,
    Course,
    Semester,
    Participant,
    CourseRecord
)
from app.course_utils import (
    create_single_course_activity,
    modify_course_activity,
)
from app.utils import (
    get_person_or_org,
    record_modification,
)

from datetime import datetime, timedelta
from django.db import transaction
from collections import Counter
import json

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
        if user_type != "Organization":
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


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[showCourseRecord]', record_user=True)
def showCourseRecord(request):

   
    edit_able = get_setting("course_record_editable")
    edit_able = bool(edit_able)
    # ----身份检查----
    valid, user_type, display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身

    if user_type == "Person":   
        return redirect(message_url(wrong('学生账号不能访问此界面！')))
    if me.otype.otype_name != "书院课程":
        return redirect(message_url(wrong('非书院课程组织账号不能访问此界面！')))
    year = get_setting("semester_data/year")
    semester = get_setting("semester_data/semester")
    course_info = {
        'course' : me.oname,
        'year' : year,
        'semester' : semester,
    }     
    # ---- 收集本学期的已完成的活动中的签到信息（开放修改功能前）----
        # ---- 收集当前小组成员信息 ----
    positions  = Position.objects.activated().filter(org = me, 
        person__identity = NaturalPerson.Identity.STUDENT)
    course = Course.objects.activated().filter(organization = me)[0]
    all_positions = {position.person:position.pos for position in positions}
    #all_positions: 储存 小组成员：职位 的一个字典

        # ---- 收集本学期已完成活动 ----
    activities=Activity.objects.activated().filter(
        organization_id=me,status=Activity.Status.END,
        category=Activity.ActivityCategory.COURSE)
        # ---- 统计签到情况 -----
    all_participants = Participant.objects.filter(
        activity_id__in = activities ,
        person_id__in = list(all_positions.keys()),
        status = Participant.AttendStatus.ATTENDED ,
    ).values_list("person_id__person_id__username", flat=True)
    # "person_id__person_id__username" 是学号

    record_list = dict(Counter(list(all_participants)))

    for key in all_positions.keys():     
        # record_list 是一个储存（活动成员：参与次数）的一个字典，
        # 可能存在成员不在此字典中的可能，因为有可能一次也没参加
        if str(key.person_id) not in list(record_list.keys()):
            key.times = 0 #一次也没参加活动
        else: key.times = record_list[str(key.person_id)]
    all_positions = dict(sorted(all_positions.items(), key=lambda x: x[1]))
    #按照职位排序，前端需要
    
    for person in list(all_positions.keys()): #record_list.keys()即为所有成员的列表
        # 下面两个属性用于传入前端
        person.avatar_path = utils.get_user_ava(person, "Person")
        person.pos =me.otype.get_name(all_positions[person])


    record_search = CourseRecord.objects.filter(#查找此课程本学期所有成员的学时表
        course = course,
        year = course_info['year'],
        semester = Semester.get(course_info['semester']),
    )
    if edit_able:
        #-----新建空学时表-----
        for person in all_positions.keys(): 
            record_search_person = record_search.filter(person = person)
            if not record_search_person.exists():
                record_create = CourseRecord.objects.create(
                    person = person,
                    course = course,
                    attend_times = person.times,
                    total_hours = person.times*2,
                    year = year,
                    semester = Semester.get(course_info['semester']),
                )
                loginfo = "Organization"+me.oname+" create CourseRecord: <"+ record_create.course.name\
                    +" times:"+str(record_create.attend_times)+" hours:"+str(record_create.total_hours) +">"
                record_modification(me.organization_id, info=loginfo)
            else: #可能在创建学时表之后又有新的活动，所以更新参加次数
                with transaction.atomic():
                    record_search_person.update(attend_times = person.times)
    # 可编辑状态时传入前端      
    for record in record_search:
        person = record.person
        person.pos = me.otype.get_name(all_positions[person])
        person.avatar_path = utils.get_user_ava(person, "Person")
        record.total_hours = int(record.total_hours)

    if request.method == "POST":
        if not edit_able:
            # 由于未开放修改功能时前端无法通过表格和按钮修改和提交，
            # 所以如果出现POST请求，则为非法情况
            return redirect(message_url(wrong('目前尚未开放修改功能，请不要进行任何尝试！')))
        elif request.is_ajax(): #从前端将修改后的表格传入
            post_datas = json.loads(request.POST.get('data'))
            for point in range(len(post_datas)):
                post_data = post_datas[point]
                post_data[0] = post_data[0].replace(" ","").replace("\n","") #前端传入的时候格式有点奇怪，会有一些空格和换行符
                person_edit = list(all_positions.keys())[point]
                if str(person_edit) != post_data[0]: #只有非法修改流量包的数据才会这样
                    return redirect(message_url(wrong('请勿尝试篡改传出数据!')))

                # --- 修改学时表 ---
                record_edited = record_search.filter(person = person_edit)
                old_times = record_edited[0].attend_times
                old_hours = record_edited[0].total_hours
                with transaction.atomic():
                    record_edited.update(
                        attend_times = int(post_data[2]),
                        total_hours = int(post_data[3])
                    )
                loginfo = "Organization"+me.oname+" change CourseRecord from <"+" times:"+\
                    str(old_times)+" hours:"+str(old_hours)+"> to <"+" times:"+\
                    str(record_edited[0].attend_times) + " hours:"+str(record_edited[0].total_hours) +">"
                record_modification(me.organization_id, info=loginfo)

    bar_display = utils.get_sidebar_and_navbar(request.user, "课程学时")
    return render(request, "course_record.html", locals())