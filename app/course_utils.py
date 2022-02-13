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
    CourseParticipant,
    Semester,
)
from app.utils import get_person_or_org
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
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Sum

from app.scheduler import scheduler


__all__ = [
    'course_activity_base_check',
    'create_single_course_activity',
    'modify_course_activity',
    'cancel_course_activity',
    'registration_status_change',
    'course_to_display',
    'change_course_status',
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


def course_to_display(courses, user, detail=False):
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

    # 预取，减少数据库查询次数
    courses = courses.select_related("organization").prefetch_related(
        "participant_set")

    # 获取课程的基本信息
    for course in courses:
        course_info = {}
        course_info["course_id"] = course.id
        course_info["name"] = course.name
        course_info["capacity"] = course.capacity
        course_info["current_participants"] = course.current_participants
        course_info["times"] = course.times  # 课程周数
        course_info["type"] = course.get_type_display()  # 课程类型
        course_info["status"] = course.get_status_display()  # 课程所处的选课阶段
        course_info["avatar_path"] = course.organization.avatar.name
        # 暂时不用这些信息
        # if course.stage1_start:
        #     course_info["stage1_start"] = course.stage1_start.strftime(
        #         "%Y-%m-%d %H:%M")
        # if course.stage1_end:
        #     course_info["stage1_end"] = course.stage1_end.strftime(
        #         "%Y-%m-%d %H:%M")
        # if course.stage2_start:
        #     course_info["stage2_start"] = course.stage2_start.strftime(
        #         "%Y-%m-%d %H:%M")
        # if course.stage2_end:
        #     course_info["stage2_end"] = course.stage2_end.strftime(
        #         "%Y-%m-%d %H:%M")

        # 当前学生的选课状态
        if course.participant_set.exists():
            course_info["student_status"] = course.participant_set.get(
                course=course, person=user).get_status_display()
        else:
            course_info["student_status"] = "未选课"

        course_time = []
        for time in course.time_set.all():
            course_time.append(process_time(time.start, time.end))
        course_info["time_set"] = course_time

        # 在课程详情页才展示的信息

        if detail:
            course_info["classroom"] = course.classroom
            course_info["teacher"] = course.teacher
            course_info["introduction"] = course.introduction
            course_info["photo"] = course.photo.name  # 图片在media文件夹内的路径

            # 暂时不启用意愿点机制
            # course_info["bidding"] = int(course.bidding)

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
def change_course_status(course_id, cur_status, to_status):
    """
    作为定时任务，在课程设定的时间改变课程的选课阶段

    使用方法:
        scheduler.add_job(change_course_status, "date", 
        id=f"course_{course_id}_{to_status}, run_date, args)

    参数:
        course_id: course对象的主键
        cur_status: course对象当前的选课状态
        to_status: 希望course变为的选课状态
    
    注意:
        1、暂时没有做时间一致性的检查。考虑到在开课填表的时候，前端要进行时间的检查，
        所以这里暂时可以不检查时间。
        2、在开设课程的时候将该函数添加到定时任务中，可以参考活动开设的相关操作。
    """
    try:
        course = Course.objects.get(id=course_id)
    except:
        raise AssertionError("课程ID不存在")

    # 分别是预选和补退选的开始和结束时间

    stage1_start = course.stage1_start
    stage1_end = course.stage1_end
    stage2_start = course.stage2_start
    stage2_end = course.stage2_end
    now = datetime.now()

    # 状态随时间的变化: WAITING-STAGE1-WAITING-STAGE2-END
    # 以下进行状态的合法性检查

    if cur_status is not None:
        assert cur_status == course.status, \
               f"希望的状态是{cur_status}，但实际状态为{course.status}"
        if cur_status == Course.Status.WAITING:
            if now < stage1_end:  # 开始预选，那么当前时间一定比预选结束的时间早
                assert to_status == Course.Status.STAGE1, \
                f"不能从{cur_status}变更到{to_status}"
            else:
                assert to_status == Course.Status.STAGE2, \
                f"不能从{cur_status}变更到{to_status}"
        elif cur_status == Course.Status.STAGE1:
            assert to_status == Course.Status.WAITING, \
            f"不能从{cur_status}变更到{to_status}"
        elif cur_status == Course.Status.STAGE2:
            assert to_status == Course.Status.END, \
            f"不能从{cur_status}变更到{to_status}"
        else:
            raise AssertionError("选课已经结束，不能再变化状态")
    else:
        raise AssertionError("未提供当前状态，不允许进行选课状态修改")

    if to_status == Course.Status.WAITING and now >= stage1_end:
        # 预选结束，进行抽签
        draw_lots(course)

    # 其他情况只需要更新课程的选课阶段

    with transaction.atomic():
        Course.objects.select_for_update().filter(id=course_id).update(
            status=to_status)

    if to_status == Course.Status.END:
        # 将选课成功的同学批量加入小组
        participants = CourseParticipant.objects.filter(
            course=course,
            status=CourseParticipant.Status.SUCCESS).select_related('person')
        organization = course.organization
        positions = []
        for participant in participants:
            # 检查是否已经加入小组
            if not Position.objects.filter(person=participant.person,
                                           org=organization).exists():
                position = Position(person=participant.person,
                                    org=organization,
                                    in_semester=Semester.get(
                                        get_setting("semester_data/semester")))
                positions.append(position)
        if positions:
            with transaction.atomic():
                Position.objects.bulk_create(positions)
