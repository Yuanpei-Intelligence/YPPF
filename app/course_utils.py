"""
course_utils.py

course_views.py的依赖函数

registration_status_check: 检查学生选课状态变化的合法性
registration_status_change: 改变学生选课状态
course_to_display: 把课程信息转换为方便前端呈现的形式
draw_lots: 预选阶段结束时执行抽签
change_course_status: 改变课程的选课阶段
remaining_willingness_point（暂不启用）: 计算学生剩余的意愿点数
process_time: 把datetime对象转换成人类可读的时间表示
"""
from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Activity,
    Notification,
    ActivityPhoto,
    Position,
    Participant,
    Course,
    CourseTime,
    CourseParticipant,
    CourseRecord,
    Semester,
)
from app.utils import (
    get_person_or_org,
    if_image,
)
from app.notification_utils import (
    bulk_notification_create,
    notification_create,
    notification_status_change,
)
from app.activity_utils import (
    changeActivityStatus,
    check_ac_time,
    notifyActivity,
)
from app.wechat_send import WechatApp, WechatMessageLevel

from random import sample
from collections import Counter
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Sum, Prefetch

from app.scheduler import scheduler


__all__ = [
    'course_activity_base_check',
    'create_single_course_activity',
    'modify_course_activity',
    'cancel_course_activity',
    'registration_status_change',
    'course_to_display',
    'change_course_status',
    'course_base_check',
    'create_course',
    'cal_participate_num',
    'check_post_and_modify',
]


def course_activity_base_check(request):
    '''检查课程活动，是activity_base_check的简化版，失败时抛出AssertionError'''
    context = dict()

    # 读取活动名称和地点，检查合法性
    context["title"] = request.POST["title"]
    # context["introduction"] = request.POST["introduction"] # 暂定不需要简介
    context["location"] = request.POST["location"]
    assert len(context["title"]) > 0, "标题不能为空"
    # assert len(context["introduction"]) > 0 # 暂定不需要简介
    assert len(context["location"]) > 0, "地点不能为空"

    # 读取活动时间，检查合法性
    act_start = datetime.strptime(
        request.POST["lesson_start"], "%Y-%m-%d %H:%M")  # 活动开始时间
    act_end = datetime.strptime(
        request.POST["lesson_end"], "%Y-%m-%d %H:%M")  # 活动结束时间
    context["start"] = act_start
    context["end"] = act_end
    assert check_ac_time(act_start, act_end), "活动时间非法"

    # 默认需要签到
    context["need_checkin"] = True

    return context


def create_single_course_activity(request):
    '''
    创建单次课程活动，是create_activity的简化版
    '''
    context = course_activity_base_check(request)

    # 查找是否有类似活动存在
    old_ones = Activity.objects.activated().filter(
        title=context["title"],
        start=context["start"],
        # introduction=context["introduction"], # 暂定不需要简介
        location=context["location"],
        category=Activity.ActivityCategory.COURSE,  # 查重时要求是课程活动
    )
    if len(old_ones):
        assert len(old_ones) == 1, "创建活动时，已存在的相似活动不唯一"
        return old_ones[0].id, False

    # 获取默认审核老师
    default_examiner_name = get_setting("course/audit_teacher")
    examine_teacher = NaturalPerson.objects.get(
        name=default_examiner_name, identity=NaturalPerson.Identity.TEACHER)

    # 创建活动
    org = get_person_or_org(request.user, "Organization")
    activity = Activity.objects.create(
        title=context["title"],
        organization_id=org,
        examine_teacher=examine_teacher,
        # introduction=context["introduction"],  # 暂定不需要简介
        location=context["location"],
        start=context["start"],
        end=context["end"],
        category=Activity.ActivityCategory.COURSE,
        need_checkin=True,  # 默认需要签到

        # 因为目前没有报名环节，活动状态在活动开始前默认都是WAITING，按预审核活动的逻辑
        recorded=True,
        status=Activity.Status.WAITING,

        # capacity, URL, budget, YQPoint, bidding,
        # apply_reason, inner, source, end_before均为default
    )

    # 让课程小组成员参与本活动
    positions = Position.objects.activated().filter(org=activity.organization_id)
    for position in positions:
        Participant.objects.create(
            activity_id=activity, person_id=position.person,
            status=Participant.AttendStatus.APLLYSUCCESS,
        )
    activity.current_participants = len(positions)
    activity.save()

    # 通知课程小组成员
    notifyActivity(activity.id, "newActivity")

    # 引入定时任务：提前15min提醒、活动状态由WAITING变PROGRESSING再变END
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
                      run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
                      run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
                      run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
    activity.save()

    # 使用一张默认图片以便viewActivity, examineActivity等页面展示
    tmp_pic = '/static/assets/img/announcepics/1.JPG'
    ActivityPhoto.objects.create(
        image=tmp_pic, type=ActivityPhoto.PhotoType.ANNOUNCE, activity=activity)

    # 通知审核老师
    notification_create(
        receiver=examine_teacher.person_id,
        sender=request.user,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="您有一个单次课程活动待审批",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app": WechatApp.AUDIT},
    )

    return activity.id, True


def modify_course_activity(request, activity):
    '''
    修改单次课程活动信息，是modify_activity的简化版
    成功无返回值，失败返回错误消息
    '''
    # 课程活动无需报名，在开始前都是等待中的状态
    if activity.status != Activity.Status.WAITING:
        return "课程活动只有在等待状态才能修改。"

    context = course_activity_base_check(request)

    # 记录旧信息（以便发通知），写入新信息
    old_title = activity.title
    activity.title = context["title"]
    # activity.introduction = context["introduction"]# 暂定不需要简介
    old_location = activity.location
    activity.location = context["location"]
    old_start = activity.start
    activity.start = context["start"]
    old_end = activity.end
    activity.end = context["end"]
    activity.save()

    # 目前只要编辑了活动信息，无论活动处于什么状态，都通知全体选课同学
    # if activity.status != Activity.Status.APPLYING and activity.status != Activity.Status.WAITING:
    #     return

    # 写通知
    to_participants = [f"您参与的书院课程活动{old_title}发生变化"]
    if old_title != activity.title:
        to_participants.append(f"活动更名为{activity.title}")
    if old_location != activity.location:
        to_participants.append(f"活动地点修改为{activity.location}")
    if old_start != activity.start:
        to_participants.append(
            f"活动开始时间调整为{activity.start.strftime('%Y-%m-%d %H:%M')}")

    # 更新定时任务
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
                      run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
                      run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
                      run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)

    # 发通知
    notifyActivity(activity.id, "modification_par", "\n".join(to_participants))


def cancel_course_activity(request, activity):
    '''
    取消单次课程活动，是cancel_activity的简化版，在聚合页面被调用

    在聚合页面中，应确保activity是课程活动，并且应检查activity.status，
    如果不是WAITING或PROGRESSING，不应调用本函数

    成功无返回值，失败返回错误消息
    （或者也可以在聚合页面判断出来能不能取消）
    '''
    # 只有WAITING和PROGRESSING有可能修改
    if activity.status not in [
        Activity.Status.WAITING,
        Activity.Status.PROGRESSING,
    ]:
        return f"课程活动状态为{activity.get_status_display()}，不可取消。"

    # 课程活动已于一天前开始则不能取消，这一点也可以在聚合页面进行判断
    if activity.status == Activity.Status.PROGRESSING:
        if activity.start.day != datetime.now().day:
            return "课程活动已于一天前开始，不能取消。"

    # 取消活动
    activity.status = Activity.Status.CANCELED
    # 目前只要取消了活动信息，无论活动处于什么状态，都通知全体选课同学
    notifyActivity(activity.id, "modification_par",
                   f"您报名的书院课程活动{activity.title}已取消（活动原定开始于{activity.start.strftime('%Y-%m-%d %H:%M')}）。")

    # 删除老师的审核通知（如果有）
    notification = Notification.objects.get(
        relate_instance=activity,
        typename=Notification.Type.NEEDDO
    )
    notification_status_change(notification, Notification.Status.DELETE)

    # 取消定时任务（需要先判断一下是否已经被执行了）
    if activity.start - timedelta(minutes=15) > datetime.now():
        scheduler.remove_job(f"activity_{activity.id}_remind")
    if activity.start > datetime.now():
        scheduler.remove_job(
            f"activity_{activity.id}_{Activity.Status.PROGRESSING}")
    if activity.end > datetime.now():
        scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.END}")

    activity.save()


def remaining_willingness_point(user):
    """
    计算剩余的意愿点
    """
    raise NotImplementedError("暂时不使用意愿点")
    # 当前用户已经预选的课
    # 由于participant可能为空，重新启用的时候注意修改代码
    courses = Course.objects.filter(
        participant_set__person=user,
        participant_set__status=CourseParticipant.Status.SELECT)

    initial_point = 99  # 初始意愿点
    cost_point = courses.aggregate(Sum('bidding'))  # 已经使用的意愿点

    if cost_point:
        # cost_point可能为None
        return initial_point - cost_point['bidding__sum']
    else:
        return initial_point


def registration_status_check(course_status, cur_status, to_status):
    """
    判断选课状态的变化是否合法

    说明:
        预选阶段可能的状态变化: SELECT <-> UNSELECT
        补退选阶段可能的状态变化: SUCCESS -> UNSELECT; FAILED -> SUCCESS; UNSELECT -> SUCCESS
    注意:
        抛出AssertionError，在调用处解决。
    """
    if course_status == Course.Status.STAGE1:
        assert ((cur_status == CourseParticipant.Status.SELECT
                 and to_status == CourseParticipant.Status.UNSELECT)
                or (cur_status == CourseParticipant.Status.UNSELECT
                    and to_status == CourseParticipant.Status.SELECT))
    else:
        assert ((cur_status == CourseParticipant.Status.SUCCESS
                 and to_status == CourseParticipant.Status.UNSELECT)
                or (cur_status == CourseParticipant.Status.FAILED
                    and to_status == CourseParticipant.Status.SUCCESS)
                or (cur_status == CourseParticipant.Status.UNSELECT
                    and to_status == CourseParticipant.Status.SUCCESS))


@log.except_captured(return_value=True,
                     record_args=True,
                     status_code=log.STATE_WARNING,
                     source='course_utils[registration_status_change]')
def registration_status_change(course_id, user, action=None):
    """
    学生点击选课或者取消选课后，用该函数更改学生的选课状态

    参数:
        course_id: Course的主键，
        action: 是希望对课程进行的操作，可能为"select"或"cancel"

    注意: 
        非选课阶段，不应该进入这个函数！
    """
    context = {}
    context["warn_code"] = 1
    context["warn_message"] = "在修改选课状态的过程中发生错误，请联系管理员！"

    # 在外部保证课程ID是存在的
    course = Course.objects.get(id=course_id)
    course_status = course.status

    # 设置初始值，后面可以省略一些判断
    to_status = CourseParticipant.Status.UNSELECT

    if (course_status != Course.Status.STAGE1
            and course_status != Course.Status.STAGE2):
        context["warn_message"] = "在非选课阶段不能选课！"
        return context

    # 选课信息
    participant_info, _ = CourseParticipant.objects.get_or_create(
        course_id=course_id, person=user)
    cur_status = participant_info.status

    if action == "select":
        if course_status == Course.Status.STAGE1:
            to_status = CourseParticipant.Status.SELECT
        else:
            to_status = CourseParticipant.Status.SUCCESS

        # 选课不能超过6门
        if CourseParticipant.objects.filter(
                course=course,
                person=user,
                status__in=[
                    CourseParticipant.Status.SELECT,
                    CourseParticipant.Status.SUCCESS,
                ]).count() >= 6:
            context["warn_message"] = "每位同学同时预选或选上的课程数最多为6门！"
            return context

    # 如果action为取消预选或退选，to_status直接使用初始值即可

    # 检查当前选课状态、选课阶段和操作的一致性
    try:
        registration_status_check(course_status, cur_status, to_status)
    except AssertionError:
        context["warn_message"] = "非法的选课状态修改！"
        return context

    # 暂时不使用意愿点选课
    # if (course_status == Course.Status.STAGE1
    #         and remaining_willingness_point(user) < course.bidding):
    #     context["warn_message"] = "剩余意愿点不足"

    # 更新选课状态
    try:
        with transaction.atomic():
            if to_status == CourseParticipant.Status.UNSELECT:
                Course.objects.filter(id=course_id).select_for_update().update(
                    current_participants=F("current_participants") - 1)
                CourseParticipant.objects.filter(
                    course__id=course_id, person=user).update(status=to_status)
                context["warn_code"] = 2
                context["warn_message"] = "成功取消选课！"
            else:
                # 处理并发问题
                course = Course.objects.select_for_update().get(id=course_id)
                if (course_status == Course.Status.STAGE2
                        and course.current_participants >= course.capacity):
                    context["warn_code"] = 1
                    context["warn_message"] = "选课人数已满！"
                else:
                    course.current_participants = course.current_participants + 1
                    course.save()

                    # 由于不同用户之间的状态不共享，这个更新应该可以不加锁
                    CourseParticipant.objects.filter(
                        course__id=course_id,
                        person=user).update(status=to_status)
                    context["warn_code"] = 2
                    context["warn_message"] = "选课成功！"
    except:
        return context
    return context


def process_time(start, end) -> str:
    """
    把datetime对象转换成人类可读的时间表示
    """
    chinese_display = ["一", "二", "三", "四", "五", "六", "日"]
    start_time = start.strftime("%H:%M")
    end_time = end.strftime("%H:%M")
    return f"周{chinese_display[start.weekday()]} {start_time}-{end_time}"


@log.except_captured(return_value=[],
                     record_args=True,
                     status_code=log.STATE_WARNING,
                     source='course_utils[course_to_display]')
def course_to_display(courses, user, detail=False) -> list:
    """
    方便前端呈现课程信息

    参数:
        courses: 一个Course对象QuerySet
        user: 当前用户对应的NaturalPerson对象
        detail: 是否显示课程的详细信息，默认为False
    返回值:
        返回一个列表，列表中的每个元素是一个课程信息的字典
    """
    display = []

    # TODO：task10 ljy 2022-02-14
    # 在课程详情页的前端完成后，适当调整向前端传递的字段

    if detail:
        courses = courses.select_related('organization').prefetch_related(
            "time_set")
    else:
        # 预取，同时不查询不需要的字段
        courses = courses.defer(
            "classroom",
            "teacher",
            "introduction",
            "photo",
            "teaching_plan",
            "record_cal_method",
        ).select_related('organization').prefetch_related(
            Prefetch('participant_set',
                     queryset=CourseParticipant.objects.filter(person=user),
                     to_attr='participants'), "time_set")

    # 获取课程的基本信息
    for course in courses:
        course_info = {}

        course_info["name"] = course.name
        course_info["times"] = course.times  # 课程周数
        course_info["type"] = course.get_type_display()  # 课程类型
        course_info["avatar_path"] = course.organization.get_user_ava()

        course_time = []
        for time in course.time_set.all():
            course_time.append(process_time(time.start, time.end))
        course_info["time_set"] = course_time

        if detail:
            # 在课程详情页才展示的信息
            course_info["classroom"] = course.classroom
            course_info["teacher"] = course.teacher
            course_info["introduction"] = course.introduction
            course_info["teaching_plan"] = course.teaching_plan
            course_info["record_cal_method"] = course.record_cal_method
            course_info["photo_path"] = course.get_photo_path()
            course_info["organization_name"] = course.organization.oname
            display.append(course_info)
            continue

        course_info["course_id"] = course.id
        course_info["capacity"] = course.capacity
        course_info["current_participants"] = course.current_participants
        course_info["status"] = course.get_status_display()  # 课程所处的选课阶段

        # 暂时不启用意愿点机制
        # course_info["bidding"] = int(course.bidding)

        # 当前学生的选课状态（注：course.participants是一个list）
        if course.participants:
            course_info["student_status"] = course.participants[
                0].get_status_display()
        else:
            course_info["student_status"] = "未选课"

        display.append(course_info)

    return display


@log.except_captured(return_value=True,
                     record_args=True,
                     status_code=log.STATE_WARNING,
                     source='course_utils[draw_lots]')
def draw_lots(course):
    """
    等额抽签选出成功选课的学生，并修改学生的选课状态

    参数:
        course: 待抽签的课程
    """
    participants = CourseParticipant.objects.filter(
        course=course,
        status=CourseParticipant.Status.SELECT).select_related()

    participants_num = participants.count()
    if participants_num <= 0:
        return

    participants_id = list(participants.values_list("id", flat=True))
    capacity = course.capacity

    if participants_num <= capacity:
        # 选课人数少于课程容量，不用抽签
        with transaction.atomic():
            CourseParticipant.objects.filter(
                course=course).select_for_update().update(
                    status=CourseParticipant.Status.SUCCESS)
            Course.objects.filter(id=course.id).select_for_update().update(
                current_participants=participants_num)
    else:
        # 抽签；可能实现得有一些麻烦
        lucky_ones = sample(participants_id, capacity)
        unlucky_ones = list(set(participants_id).difference(set(lucky_ones)))
        with transaction.atomic():
            # 不确定是否要加悲观锁
            CourseParticipant.objects.filter(
                id__in=lucky_ones).select_for_update().update(
                    status=CourseParticipant.Status.SUCCESS)
            CourseParticipant.objects.filter(
                id__in=unlucky_ones).select_for_update().update(
                    status=CourseParticipant.Status.FAILED)
            Course.objects.filter(id=course.id).select_for_update().update(
                current_participants=capacity)

    # 给选课成功的同学发送通知
    receivers = CourseParticipant.objects.filter(
        course=course,
        status=CourseParticipant.Status.SUCCESS,
    ).values_list("person", flat=True)
    receivers = User.objects.filter(id__in=receivers)
    sender = course.organization.organization_id
    typename = Notification.Type.NEEDREAD
    title = Notification.Title.ACTIVITY_INFORM
    content = f"您好！您已成功选上课程《{course.name}》！"

    # 课程详情页面
    URL = f"/viewCourse/?courseid={course.id}"

    # 批量发送通知
    bulk_notification_create(
        receivers=receivers,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
        URL=URL,
        publish_to_wechat=True,
        publish_kws={
            "app": WechatApp.TO_PARTICIPANT,
            "level": WechatMessageLevel.IMPORTANT,
        },
    )

    # 给选课失败的同学发送通知

    receivers = CourseParticipant.objects.filter(
        course=course,
        status=CourseParticipant.Status.FAILED,
    ).values_list("person", flat=True)
    receivers = User.objects.filter(id__in=receivers)
    content = f"很抱歉通知您，您未选上课程《{course.name}》。"
    if len(receivers) > 0:
        bulk_notification_create(
            receivers=receivers,
            sender=sender,
            typename=typename,
            title=title,
            content=content,
            URL=URL,
            publish_to_wechat=True,
            publish_kws={
                "app": WechatApp.TO_PARTICIPANT,
                "level": WechatMessageLevel.IMPORTANT,
            },
        )


@log.except_captured(return_value=True,
                     record_args=True,
                     status_code=log.STATE_WARNING,
                     source='course_utils[change_course_status]')
def change_course_status(cur_status, to_status):
    """
    作为定时任务，在课程设定的时间改变课程的选课阶段

    使用方法:
        scheduler.add_job(change_course_status, "date", 
        id=f"course_{course_id}_{to_status}, run_date, args)

    参数:
        to_status: 希望course变为的选课状态
    """

    # 以下进行状态的合法性检查
    if cur_status is not None:
        if cur_status == Course.Status.WAITING:
                assert to_status == Course.Status.STAGE1, \
                f"不能从{cur_status}变更到{to_status}"
        elif cur_status == Course.Status.STAGE1:
            assert to_status == Course.Status.DRAWING, \
            f"不能从{cur_status}变更到{to_status}"
        elif cur_status == Course.Status.DRAWING:
            assert to_status == Course.Status.STAGE2, \
            f"不能从{cur_status}变更到{to_status}"
        elif cur_status == Course.Status.STAGE2:
            assert to_status == Course.Status.SELECT_END, \
            f"不能从{cur_status}变更到{to_status}"
        else:
            raise AssertionError("选课已经结束，不能再变化状态")
    else:
        raise AssertionError("未提供当前状态，不允许进行选课状态修改")
    courses = Course.objects.activated().filter(status=cur_status)
    with transaction.atomic():
        #更新目标状态
        courses.select_for_update().update(status=to_status)
        for course in courses:
            if to_status == Course.Status.DRAWING:
                # 预选结束，进行抽签
                draw_lots(course)
            elif to_status == Course.Status.SELECT_END:
                # 选课结束，将选课成功的同学批量加入小组
                participants = CourseParticipant.objects.filter(
                    course=course,
                    status=CourseParticipant.Status.SUCCESS).select_related(
                        'person')
                organization = course.organization
                positions = []
                for participant in participants:
                    # 检查是否已经加入小组
                    if not Position.objects.filter(person=participant.person,
                                                   org=organization).exists():
                        position = Position(person=participant.person,
                                            org=organization,
                                            in_semester=Semester.now())
                        positions.append(position)
                if positions:
                    with transaction.atomic():
                        Position.objects.bulk_create(positions)


def str_to_time(stage: str):
    """字符串转换成时间"""
    return datetime.strptime(stage,'%Y-%m-%d %H:%M:%S')


@log.except_captured(return_value=True,
                     record_args=True,
                     status_code=log.STATE_WARNING,
                     source='course_utils[register_selection]')
def register_selection():
    """
    添加定时任务，实现课程状态转变，每次发起课程时调用
    """

    # 预选和补退选的开始和结束时间

    year = CURRENT_ACADEMIC_YEAR
    semster = Semester.now()
    stage1_start = str_to_time(get_setting("course/yx_election_start"))
    stage1_end = str_to_time(get_setting("course/yx_election_end"))
    stage2_start = str_to_time(get_setting("course/btx_election_start"))
    stage2_end = str_to_time(get_setting("course/btx_election_end"))

    # 定时任务：修改课程状态
    scheduler.add_job(change_course_status, "date", id=f"course_selection_{year+semster}_stage1_start",
                      run_date=stage1_start, args=[Course.Status.WAITING,Course.Status.STAGE1], replace_existing=True)
    scheduler.add_job(change_course_status, "date", id=f"course_selection_{year+semster}_stage1_end",
                      run_date=stage1_end, args=[Course.Status.STAGE1,Course.Status.DRAWING], replace_existing=True)
    scheduler.add_job(change_course_status, "date", id=f"course_selection_{year+semster}_stage2_start",
                    run_date=stage2_start, args=[Course.Status.DRAWING,Course.Status.STAGE2], replace_existing=True)
    scheduler.add_job(change_course_status, "date", id=f"course_selection_{year+semster}_stage2_end",
                    run_date=stage2_end, args=[Course.Status.STAGE2,Course.Status.SELECT_END], replace_existing=True)                
    # 状态随时间的变化: WAITING-STAGE1-WAITING-STAGE2-END


def course_base_check(request):
    """
    选课单变量合法性检查并准备变量
    """
    context = dict()
    # 字符串字段合法性检查
    try:
        # name, introduction, classroom 创建时不能为空
        context["name"] = str(request.POST["name"])
        context['teacher'] = str(request.POST["teacher"])
        context["introduction"] = str(request.POST["introduction"])
        context["classroom"] = str(request.POST["classroom"])
        context["teaching_plan"] = str(request.POST["teaching_plan"])
        context["record_cal_method"] = str(request.POST["record_cal_method"])
        assert len(context["name"]) > 0, "课程名称不能为空！"
        assert len(context["introduction"]) > 0, "课程介绍不能为空！"
        assert len(context["teaching_plan"]) > 0, "教学计划不能为空！"
        assert len(context["record_cal_method"]) > 0, "学时计算方法不能为空！"
        assert len(context["classroom"]) > 0, "上课地点不能为空！"
    except Exception as e:
        return wrong(str(e))

    # int类型合法性检查

    type_num = request.POST.get("type", -1)  # 课程类型
    capacity = request.POST.get("capacity", -1)
    # context['times'] = int(request.POST["times"])    #课程上课周数
    try:
        assert type_num != "", "记得选择课程类型哦！"
        assert 0 <= int(type_num) < 5, "课程类型仅包括德智体美劳五种！"
        assert int(capacity) > 0, "课程容量应当大于0！"
    except Exception as e:
        return wrong(str(e))
    context['type'] = int(type_num)
    context['capacity'] = int(capacity)

    # 图片类型合法性检查
    try:
        announcephoto = request.FILES.get("photo")
        pic = None
        if announcephoto:
            pic = announcephoto
            assert if_image(pic) == 2, "课程预告图片文件类型错误！"
        else:
            for i in range(5):
                if request.POST.get(f'picture{i+1}'):
                    pic = request.POST.get(f'picture{i+1}')
        context["photo"] = pic
        context["QRcode"] = request.FILES.get("QRcode")
        assert if_image(context["QRcode"]) != 1, "微信群二维码图片文件类型错误！"
    except Exception as e:
        return wrong(str(e))

    # 每周课程时间合法性检查
    course_starts = request.POST.getlist("start")
    course_ends = request.POST.getlist("end")
    course_starts = [
        datetime.strptime(course_start, "%Y-%m-%d %H:%M")
        for course_start in course_starts
        if course_start != ''
    ]
    course_ends = [
        datetime.strptime(course_end, "%Y-%m-%d %H:%M")
        for course_end in course_ends
        if course_end != ''
    ]
    try:
        for i in range(len(course_starts)):
            assert check_ac_time(
                course_starts[i], course_ends[i]), f'第{i+1}次上课时间起止时间有误！'
            # 课程每周同一次课的开始和结束时间应当处于同一天
            assert course_starts[i].date(
            ) == course_ends[i].date(), f'第{i+1}次上课起止时间应当为同一天'
    except Exception as e:
        return wrong(str(e))
    context['course_starts'] = course_starts
    context['course_ends'] = course_ends

    org = get_person_or_org(request.user, "Organization")
    context['organization'] = org

    context["warn_code"] = 2
    context["warn_message"] = "合法性检查通过！"
    return context


def create_course(request, course_id=None):
    '''
    检查课程，合法时寻找该课程，不存在时创建
    返回(course.id, created)
    '''
    context = dict()

    try:
        context = course_base_check(request)
        if context["warn_code"] == 1:  # 合法性检查出错！
            return context
    except:
        return wrong("检查参数合法性时遇到不可预料的错误。如有需要，请联系管理员解决!")
    default_photo="/static/assets/img/announcepics/1.JPG"
    # 编辑已有课程
    if course_id is not None:
        try:
            course = Course.objects.get(id=int(course_id))
            with transaction.atomic():
                course_time = course.time_set.all()
                course_time.delete()
                course.name = context["name"]
                course.classroom = context["classroom"]
                course.teacher = context['teacher']
                course.introduction = context["introduction"]
                course.teaching_plan = context["teaching_plan"]
                course.record_cal_method = context["record_cal_method"]
                course.type = context['type']
                course.capacity = context["capacity"]
                course.photo = context['photo'] if context['photo'] is not None else course.photo
                if context['QRcode']:
                    course.QRcode = context["QRcode"]
                course.save()

                for i in range(len(context['course_starts'])):
                    CourseTime.objects.create(
                        course=course,
                        start=context['course_starts'][i],
                        end=context['course_ends'][i],
                    )
        except:
            return wrong("修改课程时遇到不可预料的错误。如有需要，请联系管理员解决!")
        context["cid"] = course_id
        context["warn_code"] = 2
        context["warn_message"] = "修改课程成功！"
    # 创建新课程
    else:
        try:
            with transaction.atomic():
                course = Course.objects.create(
                    name=context["name"],
                    organization=context['organization'],
                    classroom=context["classroom"],
                    teacher=context['teacher'],
                    introduction=context["introduction"],
                    teaching_plan=context["teaching_plan"],
                    record_cal_method=context["record_cal_method"],
                    type=context['type'],
                    capacity=context["capacity"],
                )
                course.photo = context['photo'] if context['photo'] is not None else default_photo
                if context['QRcode']:
                    course.QRcode = context["QRcode"]
                course.save()

                for i in range(len(context['course_starts'])):
                    CourseTime.objects.create(
                        course=course,
                        start=context['course_starts'][i],
                        end=context['course_ends'][i],
                    )
            register_selection()    #每次发起课程，创建定时任务
        except:
            return wrong("创建课程时遇到不可预料的错误。如有需要，请联系管理员解决!")
        context["cid"] = course.id
        context["warn_code"] = 2
        context["warn_message"] = "创建课程成功！"

    return context


def cal_participate_num(course: Course)-> Counter:
    """
    计算该课程对应组织所有成员的参与次数
    return {Naturalperson.id:参与次数}
    前端使用的时候直接读取字典的值就好了
    """
    org = course.organization
    activities = Activity.objects.activated().filter(
        organization_id=org,
        status=Activity.Status.END,
        category=Activity.ActivityCategory.COURSE,
    )
    all_participants = (
        Participant.objects.activated(no_unattend=True)
        .filter(activity_id__in=activities)
    ).values_list("person_id", flat=True)
    participate_num = Counter(all_participants)
    return participate_num


def check_post_and_modify(records, post_data):
    """
    records和post_data分别为原先和更新后的list
    检查post表单是否可以为这个course对应的内容，
    如果可以，修改学时
    - 返回wrong|succeed
    - 不抛出异常
    """
    try:
        # 对每一条记录而言
        for record in records:
            # 选取id作为匹配键
            key = str(record.person.id)
            assert key in post_data.keys(), "提交的人员信息不匹配，请联系管理员！"

            # 读取小时数
            hours = post_data.get(str(key), -1)
            assert float(hours) >= 0, "学时数据为负数，请检查输入数据！"
            record.total_hours = float(hours)

        CourseRecord.objects.bulk_update(records, ["total_hours"])
        return succeed("修改学时信息成功！")
    except AssertionError as e:
        # 此时相当于出现用户应该知晓的信息
        return wrong(str(e))
    except:
        return wrong("数据格式异常，请检查输入数据！")
