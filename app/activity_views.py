import os
import io
import urllib.parse
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, F
import csv
import qrcode

from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
    Activity,
    ActivityPhoto,
    Participant,
    ActivitySummary,
)
from app.activity_utils import (
    ActivityException,
    create_activity,
    modify_activity,
    accept_activity,
    reject_activity,
    apply_activity,
    cancel_activity,
    withdraw_activity,
    get_activity_QRcode,
)
from app.comment_utils import addComment, showComment
from app.utils import (
    get_person_or_org,
    escape_for_templates,
)

__all__ = [
    'viewActivity', 'getActivityInfo', 'checkinActivity',
    'addActivity', 'showActivity', 'examineActivity',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def viewActivity(request: HttpRequest, aid=None):
    """
    页面逻辑：
    1. 方法为 GET 时，展示一个活动的详情。
        a. 如果当前用户是个人，有立即报名/已报名的 button
        b. 如果当前用户是小组，并且是该活动的所有者，有修改和取消活动的 button
    2. 方法为 POST 时，通过 option 确定操作
        a. 如果修改活动，跳转到 addActivity
        b. 如果取消活动，本函数处理
        c. 如果报名活动，本函数处理 ( 还未实现 )
    # TODO
    个人操作，包括报名与取消
    ----------------------------
    活动逻辑
    1. 活动开始前一小时，不能修改活动
    2. 活动开始当天晚上之前，不能再取消活动 ( 目前用的 12 小时，感觉基本差不多 )
    """

    """
    aname = str(request.POST["aname"])  # 活动名称
    organization_id = request.POST["organization_id"]  # 小组id
    astart = request.POST["astart"]  # 默认传入的格式为 2021-07-21 21:00:00
    afinish = request.POST["afinish"]
    content = str(request.POST["content"])
    URL = str(request.POST["URL"])  # 活动推送链接
    QRcode = request.POST["QRcode"]  # 收取元气值的二维码
    capacity = request.POST["capacity"]  # 活动举办的容量
    """

    aid = int(aid)
    activity: Activity = Activity.objects.get(id=aid)
    _, user_type, html_display = utils.check_user_type(request.user)
    org = activity.organization_id
    me = utils.get_person_or_org(request.user, user_type)
    ownership = False
    if user_type == UTYPE_ORG and org == me:
        ownership = True
    examine = False
    if user_type == UTYPE_PER and activity.examine_teacher == me:
        examine = True
    if not (ownership or examine) and activity.status in [
        Activity.Status.REVIEWING,
        Activity.Status.ABORT,
        Activity.Status.REJECT,
    ]:
        return redirect(message_url(wrong('该活动暂不可见!')))

    html_display = dict()
    inform_share, alert_message = utils.get_inform_share(me)

    if request.method == "POST" and request.POST:
        option = request.POST.get("option")
        if option == "cancel":
            try:
                if activity.status in [
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
                    succeed("成功取消活动。", html_display)
            except ActivityException as e:
                wrong(str(e), html_display)
            except Exception as e:
                raise

        elif option == "edit":
            if (
                    activity.status == Activity.Status.APPLYING
                    or activity.status == Activity.Status.REVIEWING
            ):
                return redirect(f"/editActivity/{aid}")
            if activity.status == Activity.Status.WAITING:
                if activity.start + timedelta(hours=1) < datetime.now():
                    return redirect(f"/editActivity/{aid}")
                wrong(f"距离活动开始前1小时内将不再允许修改活动。如确有雨天等意外情况，请及时取消活动。", html_display)
            else:
                wrong(f"活动状态为{activity.status}, 不能修改。", html_display)

        elif option == "apply":
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=int(aid))
                    if activity.status != Activity.Status.APPLYING:
                        return redirect(message_url(wrong('活动不在报名状态!'), request.path))
                    apply_activity(request, activity)
                    if activity.bidding:
                        succeed(f"活动申请中，请等待报名结果。", html_display)
                    else:
                        succeed(f"报名成功。", html_display)
            except ActivityException as e:
                wrong(str(e), html_display)
            except Exception as e:
                raise

        elif option == "quit":
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=aid)
                    if activity.status not in [
                        Activity.Status.APPLYING,
                        Activity.Status.WAITING,
                    ]:
                        return redirect(message_url(wrong('当前状态不允许取消报名!'), request.path))
                    withdraw_activity(request, activity)
                    if activity.bidding:
                        html_display["warn_message"] = f"已取消申请。"
                    else:
                        html_display["warn_message"] = f"已取消报名。"
                    html_display["warn_code"] = 2

            except ActivityException as e:
                html_display["warn_code"] = 1
                html_display["warn_message"] = str(e)
            except Exception as e:
                raise

        elif option == "checkinoffline":
            # 进入调整签到界面
            if activity.status != Activity.Status.END:
                return redirect(message_url(wrong('活动尚未结束!'), request.path))
            if not ownership:
                return redirect(message_url(wrong('您没有调整签到信息的权限!'), request.path))
            return redirect(f"/offlineCheckinActivity/{aid}")

        elif option == "sign" or option == "enroll":  # 下载活动签到信息或者报名信息
            if not ownership:
                return redirect(message_url(wrong('没有下载权限!'), request.path))
            return utils.export_activity(activity, option)
        elif option == "cancelInformShare":
            me.inform_share = False
            me.save()
            return redirect("/welcome/")
        elif option == "ActivitySummary":
            try:
                re = ActivitySummary.objects.get(activity=activity,
                                                 status__in=[ActivitySummary.Status.WAITING, ActivitySummary.Status.CONFIRMED])
                return redirect(f"/modifyEndActivity/?apply_id={re.id}")
            except:
                return redirect(f"/modifyEndActivity/")
        else:
            return redirect(message_url(wrong('无效的请求!'), request.path))

    elif request.method == "GET":
        my_messages.transfer_message_context(request.GET, html_display)

    # 下面这些都是展示前端页面要用的
    title = activity.title
    org_name = org.oname
    org_avatar_path = org.get_user_ava()
    org_type = OrganizationType.objects.get(otype_id=org.otype_id).otype_name
    start_month = activity.start.month
    start_date = activity.start.day
    duration = activity.end - activity.start
    duration = duration - timedelta(microseconds=duration.microseconds)
    prepare_times = Activity.EndBeforeHours.prepare_times
    apply_deadline = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    introduction = activity.introduction
    show_url = True  # 前端使用量
    aURL = activity.URL
    if (aURL is None) or (aURL == ""):
        show_url = False
    bidding = activity.bidding
    current_participants = activity.current_participants
    status = activity.status
    capacity = activity.capacity
    if capacity == -1 or capacity == 10000:
        capacity = "INF"
    if activity.bidding:
        apply_manner = "抽签模式"
    else:
        apply_manner = "先到先得"
    # person 表示是否是个人而非小组
    person = False
    if user_type == UTYPE_PER:
        """
        老师能否报名活动？
        if me.identity == NaturalPerson.Identity.STUDENT:
            person = True
        """
        person = True
        try:
            participant = Participant.objects.get(
                activity_id=activity, person_id=me.id)
            # pStatus 是参与状态
            pStatus = participant.status
        except:
            pStatus = "未参与"
        if pStatus == "放弃":
            pStatus = "未参与"

    # 签到
    need_checkin = activity.need_checkin
    show_QRcode = activity.need_checkin and activity.status in [
        Activity.Status.APPLYING,
        Activity.Status.WAITING,
        Activity.Status.PROGRESSING
    ]

    if activity.inner and user_type == UTYPE_PER:
        position = Position.objects.activated().filter(
            person=me, org=activity.organization_id)
        if len(position) == 0:
            not_inner = True

    if ownership and need_checkin:
        aQRcode = get_activity_QRcode(activity)

    # 活动宣传图片 ( 一定存在 )
    photo: ActivityPhoto = activity.photos.get(
        type=ActivityPhoto.PhotoType.ANNOUNCE)
    # 不是static静态文件夹里的文件，而是上传到media/activity的图片
    firstpic = photo.get_image_path()

    # 总结图片，不一定存在
    summary_photo_exists = False
    if activity.status == Activity.Status.END:
        try:
            summary_photos = activity.photos.filter(
                type=ActivityPhoto.PhotoType.SUMMARY)
            summary_photo_exists = True
        except Exception as e:
            pass

    # 参与者, 无论报名是否通过
    participants = Participant.objects.filter(Q(activity_id=activity),
                                              Q(status=Participant.AttendStatus.APPLYING) | Q(status=Participant.AttendStatus.APLLYSUCCESS) | Q(status=Participant.AttendStatus.ATTENDED) | Q(status=Participant.AttendStatus.UNATTENDED))
    #participants_ava = [utils.get_user_ava(participant, UTYPE_PER) for participant in participants.values("person_id")] or None
    people_list = NaturalPerson.objects.activated().filter(
        id__in=participants.values("person_id"))

    # 新版侧边栏，顶栏等的呈现，采用bar_display，必须放在render前最后一步，但这里render太多了
    # TODO: 整理好代码结构，在最后统一返回
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="活动信息", title_name=title)
    # 补充一些呈现信息
    # bar_display["title_name"] = "活动信息"
    # bar_display["navbar_name"] = "活动信息"

    # 浏览次数，必须在render之前
    # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
    Activity.objects.filter(id=activity.id).update(
        visit_times=F('visit_times')+1)
    # activity.visit_times += 1
    # activity.save()
    return render(request, "activity_info.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def getActivityInfo(request: HttpRequest):
    '''
    通过GET获得活动信息表下载链接
    GET参数?activityid=id&infotype=sign[&output=id,name,gender,telephone][&format=csv|excel]
    GET参数?activityid=id&infotype=qrcode
    activity_id : 活动id
    infotype    : sign or qrcode or 其他（以后可以拓展）
        sign报名信息:
        output  : [可选]','分隔的需要返回的的field名
                    [默认]id,name,gender,telephone
        format  : [可选]csv or excel
                    [默认]csv
        qrcode签到二维码
    example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=sign
    example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=sign&output=id,wtf
    example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=sign&format=excel
    example: http://127.0.0.1:8000/getActivityInfo?activityid=1&infotype=qrcode
    TODO: 前端页面待对接
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)

    # check activity existence
    activity_id = request.GET.get("activityid", None)
    activity = Activity.objects.get(id=activity_id)

    # check organization existance and ownership to activity
    organization = utils.get_person_or_org(request.user, "organization")
    assert activity.organization_id == organization, f"{organization}不是活动的组织者"

    info_type = request.GET.get("infotype", None)
    assert info_type in ["sign", "qrcode"], "不支持的infotype"

    if info_type == "sign":  # get registration information
        # make sure registration is over
        assert activity.status != Activity.Status.REVIEWING, "活动正在审核"
        assert activity.status != Activity.Status.CANCELED, "活动已取消"
        assert activity.status != Activity.Status.APPLYING, "报名尚未截止"

        # get participants
        # are you sure it's 'Paticipant' not 'Participant' ??
        participants = Participant.objects.filter(activity_id=activity_id)
        participants = participants.filter(
            status=Participant.AttendStatus.APLLYSUCCESS
        )

        # get required fields
        output = request.GET.get("output", "id,name,gender,telephone")
        fields = output.split(",")

        # check field existence
        allowed_fields = ["id", "name", "gender", "telephone"]
        for field in fields:
            assert field in allowed_fields, f"不允许的字段名{field}"

        filename = f"{activity_id}-{info_type}-{output}"
        content = map(
            lambda paticipant: map(lambda key: paticipant[key], fields),
            participants,
        )

        format = request.GET.get("format", "csv")
        assert format in ["csv"], f"不支持的格式{format}"
        if format == "csv":
            buffer = io.StringIO()
            csv.writer(buffer).writerows(content), buffer.seek(0)
            response = HttpResponse(buffer, content_type="text/csv")
            response["Content-Disposition"] = f"attachment; filename={filename}.csv"
            return response  # downloadable

    elif info_type == "qrcode":
        # checkin begins 1 hour ahead
        assert datetime.now() > activity.start - timedelta(hours=1), "签到未开始"
        checkin_url = f"/checkinActivity?activityid={activity.id}"
        origin_url = request.scheme + "://" + request.META["HTTP_HOST"]
        checkin_url = urllib.parse.urljoin(
            origin_url, checkin_url)  # require full path

        buffer = io.BytesIO()
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(checkin_url), qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(buffer, "jpeg"), buffer.seek(0)
        return HttpResponse(buffer, content_type="img/jpeg")


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def checkinActivity(request: HttpRequest, aid=None):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type != UTYPE_PER:
        return redirect(message_url(wrong('签到失败：请使用个人账号签到')))
    try:
        np = get_person_or_org(request.user, user_type)
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        varifier = request.GET["auth"]
    except:
        return redirect(message_url(wrong('签到失败!')))
    if varifier != GLOBAL_CONF.hasher.encode(str(aid)):
        return redirect(message_url(wrong('签到失败：活动校验码不匹配')))

    # context = wrong('发生意外错误')   # 理应在任何情况都生成context, 如果没有就让包装器捕获吧
    if activity.status == Activity.Status.END:
        context = wrong("活动已结束，不再开放签到。")
    elif (
        activity.status == Activity.Status.PROGRESSING or
        (activity.status == Activity.Status.WAITING
         and datetime.now() + timedelta(hours=1) >= activity.start)
    ):
        try:
            with transaction.atomic():
                participant = Participant.objects.select_for_update().get(
                    activity_id=aid, person_id=np,
                    status__in=[
                        Participant.AttendStatus.UNATTENDED,
                        Participant.AttendStatus.APLLYSUCCESS,
                        Participant.AttendStatus.ATTENDED,
                    ]
                )
                if participant.status == Participant.AttendStatus.ATTENDED:
                    context = succeed("您已签到，无需重复签到!")
                else:
                    participant.status = Participant.AttendStatus.ATTENDED
                    participant.save()
                    context = succeed("签到成功!")
        except:
            context = wrong("您尚未报名该活动!")

    else:
        context = wrong("活动开始前一小时开放签到，请耐心等待!")

    # TODO 在 activity_info 里加更多信息
    return redirect(message_url(context, f"/viewActivity/{aid}"))


# participant checkin activity
# GET参数?activityid=id
#   activity_id : 活动id
# example: http://127.0.0.1:8000/checkinActivity?activityid=1
# TODO: 前端页面待对接
"""
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def checkinActivity(request):
    valid, user_type, html_display = utils.check_user_type(request.user)

    # check activity existence
    activity_id = request.GET.get("activityid", None)
    try:
        activity = Activity.objects.get(id=activity_id)
        if (
                activity.status != Activity.Status.WAITING
                and activity.status != Activity.Status.PROGRESSING
        ):
            html_display["warn_code"] = 1
            html_display["warn_message"] = f"签到失败：活动{activity.status}"
            return redirect("/viewActivities/")  # context incomplete
    except:
        msg = "活动不存在"
        origin = "/welcome/"
        return render(request, "msg.html", locals())

    # check person existance and registration to activity
    person = utils.get_person_or_org(request.user, "naturalperson")
    try:
        participant = Participant.objects.get(
            activity_id=activity_id, person_id=person.id
        )
        if participant.status == Participant.AttendStatus.APLLYFAILED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有参与这项活动：申请失败"
        elif participant.status == Participant.AttendStatus.APLLYSUCCESS:
            #  其实我觉得这里可以增加一个让发起者设定签到区间的功能
            #    或是有一个管理界面，管理一个“签到开关”的值
            if datetime.now().date() < activity.end.date():
                html_display["warn_code"] = 1
                html_display["warn_message"] = "签到失败：签到未开始"
            elif datetime.now() >= activity.end:
                html_display["warn_code"] = 1
                html_display["warn_message"] = "签到失败：签到已结束"
            else:
                participant.status = Participant.AttendStatus.ATTENDED
                html_display["warn_code"] = 2
                html_display["warn_message"] = "签到成功"
        elif participant.status == Participant.AttendStatus.ATTENDED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "重复签到"
        elif participant.status == Participant.AttendStatus.CANCELED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有参与这项活动：已取消"
        else:
            msg = f"不合理的参与状态：{participant.status}"
            origin = "/welcome/"
            return render(request, "msg.html", locals())
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = "您没有参与这项活动：未报名"

    return redirect("/viewActivities/")  # context incomplete
"""


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def addActivity(request: HttpRequest, aid=None):
    """
    发起活动与修改活动页
    ---------------
    页面逻辑：

    该函数处理 GET, POST 两种请求，发起和修改两类操作
    1. 访问 /addActivity/ 时，为创建操作，要求用户是小组；
    2. 访问 /editActivity/aid 时，为编辑操作，要求用户是该活动的发起者
    3. GET 请求创建活动的界面，placeholder 为 prompt
    4. GET 请求编辑活动的界面，表单的 placeholder 会被修改为活动的旧值。
    """
    # TODO 定时任务

    # 检查：不是超级用户，必须是小组，修改是必须是自己
    valid, user_type, html_display = utils.check_user_type(request.user)
    # assert valid  已经在check_user_access检查过了
    me = utils.get_person_or_org(request.user, user_type)  # 这里的me应该为小组账户
    if aid is None:
        if user_type != UTYPE_ORG:
            return redirect(message_url(wrong('小组账号才能添加活动!')))
        if me.oname == CONFIG.yqp_oname:
            return redirect("/showActivity")
        edit = False
    else:
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        if user_type == UTYPE_PER:
            html_display = utils.user_login_org(
                request, activity.organization_id)
            if html_display['warn_code'] == 1:
                return redirect(message_url(wrong(html_display["warn_message"])))
            else:  # 成功以小组账号登陆
                # 防止后边有使用，因此需要赋值
                user_type = UTYPE_ORG
                request.user = activity.organization_id.get_user()  # 小组对应user
                me = activity.organization_id  # 小组
        if activity.organization_id != me:
            return redirect(message_url(wrong("无法修改其他小组的活动!")))
        edit = True
    html_display["is_myself"] = True

    # 处理 POST 请求
    # 在这个界面，不会返回render，而是直接跳转到viewactivity，可以不设计bar_display
    if request.method == "POST" and request.POST:

        if not edit:
            with transaction.atomic():
                aid, created = create_activity(request)
                if not created:
                    return redirect(message_url(
                        succeed('存在信息相同的活动，已为您自动跳转!'),
                        f'/viewActivity/{aid}'))
                return redirect(f"/editActivity/{aid}")

        # 仅这几个阶段可以修改
        if (
                activity.status != Activity.Status.REVIEWING and
                activity.status != Activity.Status.APPLYING and
                activity.status != Activity.Status.WAITING
        ):
            return redirect(message_url(wrong('当前活动状态不允许修改!'),
                                        f'/viewActivity/{activity.id}'))

        # 处理 comment
        if request.POST.get("comment_submit"):
            # 创建活动只能在审核时添加评论
            assert not activity.valid
            context = addComment(
                request, activity, activity.examine_teacher.person_id)
            # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
            assert context["warn_code"] == 2, context["warn_message"]
            # 成功后重新加载界面
            html_display["warn_message"] = "评论成功。"
            html_display["warn_code"] = 2
            # return redirect(f"/editActivity/{aid}")
        else:
            try:
                # 只能修改自己的活动
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=aid)
                    org = get_person_or_org(request.user, UTYPE_ORG)
                    assert activity.organization_id == org
                    modify_activity(request, activity)
                html_display["warn_message"] = "修改成功。"
                html_display["warn_code"] = 2
            except ActivityException as e:
                html_display["warn_message"] = str(e)
                html_display["warn_code"] = 1
                # return redirect(f"/viewActivity/{activity.id}")

    # 下面的操作基本如无特殊说明，都是准备前端使用量
    defaultpics = [{"src": f"/static/assets/img/announcepics/{i+1}.JPG",
                    "id": f"picture{i+1}"} for i in range(5)]
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava()

    use_template = False
    if request.method == "GET" and request.GET.get("template"):
        use_template = True
        template_id = int(request.GET["template"])
        activity = Activity.objects.get(id=template_id)
    if not edit and not use_template:
        available_teachers = NaturalPerson.objects.teachers()
    else:
        org = get_person_or_org(request.user, UTYPE_ORG)

        # 没过审，可以编辑评论区
        if not activity.valid:
            commentable = True
            front_check = True
        if use_template:
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

        # 决定状态的变量
        # None/edit/examine ( 小组申请活动/小组编辑/老师审查 )
        # full_editable/accepted/None ( 小组编辑活动：除审查老师外全可修改/部分可修改/全部不可改 )
        #        full_editable 为 true 时，accepted 也为 true
        # commentable ( 是否可以评论 )

        # 下面是前端展示的变量

        title = utils.escape_for_templates(activity.title)
        location = utils.escape_for_templates(activity.location)
        apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
        # apply_end_for_js = activity.apply_end.strftime("%Y-%m-%d %H:%M")
        start = activity.start.strftime("%Y-%m-%d %H:%M")
        end = activity.end.strftime("%Y-%m-%d %H:%M")
        introduction = escape_for_templates(activity.introduction)
        url = utils.escape_for_templates(activity.URL)

        endbefore = activity.endbefore
        bidding = activity.bidding
        signscheme = "先到先得"
        if bidding:
            signscheme = "抽签模式"
        capacity = activity.capacity
        no_limit = False
        if capacity == 10000:
            no_limit = True
        examine_teacher = activity.examine_teacher.name
        status = activity.status
        available_teachers = NaturalPerson.objects.teachers()
        need_checkin = activity.need_checkin
        inner = activity.inner
        if not use_template:
            comments = showComment(activity)
        photo = str(activity.photos.get(
            type=ActivityPhoto.PhotoType.ANNOUNCE).image)
        uploaded_photo = False
        if str(photo).startswith("activity"):
            uploaded_photo = True
            photo_path = photo
            photo = os.path.basename(photo)
        else:
            photo_id = "picture" + os.path.basename(photo).split(".")[0]

    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    if not edit:
        bar_display = utils.get_sidebar_and_navbar(request.user, "活动发起")
    else:
        bar_display = utils.get_sidebar_and_navbar(request.user, "修改活动")

    return render(request, "activity_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def showActivity(request: HttpRequest):
    """
    活动信息的聚合界面
    只有老师和小组才能看到，老师看到检查者是自己的，小组看到发起方是自己的
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身
    is_teacher = False  # 该变量同时用于前端
    if user_type == UTYPE_PER:
        try:
            person = utils.get_person_or_org(request.user, user_type)
            is_teacher = person.is_teacher()
            assert is_teacher
        except:
            return redirect(message_url(wrong('学生账号不能进入活动立项页面！')))
    if is_teacher:
        all_instances = {
            "undone":   Activity.objects.activated(
                only_displayable=False).filter(examine_teacher=me.id, valid=False),
            "done":     Activity.objects.activated(
                only_displayable=False).filter(examine_teacher=me.id, valid=True)
        }
    else:
        all_instances = {
            "undone":   Activity.objects.activated(
                only_displayable=False).filter(organization_id=me.id, valid=False),
            "done":     Activity.objects.activated(
                only_displayable=False).filter(organization_id=me.id, valid=True)
        }

    all_instances = {key: value.order_by(
        "-modify_time", "-time") for key, value in all_instances.items()}
    bar_display = utils.get_sidebar_and_navbar(request.user, "活动立项")

    # 前端不允许元气值中心创建活动
    if user_type == UTYPE_ORG and me.oname == CONFIG.yqp_oname:
        YQPoint_Source_Org = True

    return render(request, "activity_show.html", locals())


@login_required(redirect_field_name="origin")
@logger.secure_view()
def examineActivity(request: HttpRequest, aid):
    valid, user_type, html_display = utils.check_user_type(request.user)
    assert valid
    assert user_type == UTYPE_PER
    me = utils.get_person_or_org(request.user)
    activity = Activity.objects.get(id=int(aid))
    assert activity.examine_teacher == me

    html_display["is_myself"] = True

    if request.method == "POST" and request.POST:

        if (
                activity.status != Activity.Status.REVIEWING and
                activity.status != Activity.Status.APPLYING and
                activity.status != Activity.Status.WAITING
        ):
            return redirect(message_url(wrong('当前活动状态不可审核!')))
        if activity.valid:
            return redirect(message_url(succeed('活动已审核!')))

        if request.POST.get("comment_submit"):
            context = addComment(
                request, activity, activity.organization_id.get_user())
            # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
            assert context["warn_code"] == 2
            html_display["warn_message"] = "评论成功。"
            html_display["warn_code"] = 2

        elif request.POST.get("review_accepted"):
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(
                    id=int(aid)
                )
                accept_activity(request, activity)
            html_display["warn_message"] = "活动已通过审核。"
            html_display["warn_code"] = 2
        else:
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(
                    id=int(aid)
                )
                reject_activity(request, activity)
            html_display["warn_message"] = "活动已被拒绝。"
            html_display["warn_code"] = 2

    # 状态量，无可编辑量
    examine = True
    commentable = not activity.valid
    if (
            activity.status != Activity.Status.REVIEWING and
            activity.status != Activity.Status.APPLYING and
            activity.status != Activity.Status.WAITING
    ):
        commentable = False

    # 展示变量
    title = utils.escape_for_templates(activity.title)
    location = utils.escape_for_templates(activity.location)
    apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
    introduction = escape_for_templates(activity.introduction)

    url = utils.escape_for_templates(activity.URL)
    endbefore = activity.endbefore
    bidding = activity.bidding
    signscheme = "先到先得"
    if bidding:
        signscheme = "投点参与"
    capacity = activity.capacity
    no_limit = False
    if capacity == 10000:
        no_limit = True
    examine_teacher = activity.examine_teacher.name
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    html_display["app_avatar_path"] = activity.organization_id.get_user_ava()
    html_display["applicant_name"] = activity.organization_id.oname
    bar_display = utils.get_sidebar_and_navbar(request.user)
    status = activity.status
    comments = showComment(activity)

    examine_pic = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
    # 不是static静态文件夹里的文件，而是上传到media/activity的图片
    if str(examine_pic.image)[0] == 'a':
        examine_pic.image = MEDIA_URL + str(examine_pic.image)
    intro_pic = examine_pic.image

    need_checkin = activity.need_checkin

    bar_display = utils.get_sidebar_and_navbar(request.user, "活动审核")
    # bar_display["title_name"] = "审查活动"
    # bar_display["narbar_name"] = "审查活动"
    return render(request, "activity_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def offlineCheckinActivity(request: HttpRequest, aid):
    '''
    修改签到记录，只有举办活动的组织账号可查看和修改

    :param request: 修改请求
    :type request: HttpRequest
    :param aid: 活动id
    :type aid: int
    :return: 修改签到页面
    :rtype: HttpResponse
    '''
    _, user_type, _ = utils.check_user_type(request.user)
    me = get_person_or_org(request.user, user_type)
    aid = int(aid)
    src = request.GET.get('src')
    activity = Activity.objects.get(id=aid)
    assert me == activity.organization_id and user_type == UTYPE_ORG

    member_list = Participant.objects.filter(
        activity_id=aid,
        status__in=[
            Participant.AttendStatus.UNATTENDED,
            Participant.AttendStatus.ATTENDED,
        ])

    if request.method == "POST" and request.POST:
        option = request.POST.get("option")
        if option == "saveSituation":
            # 修改签到状态

            member_userids = member_list.values_list("person_id", flat=True)
            member_attend, member_unattend = [], []
            for person_id in member_userids:
                checkin = request.POST.get(f"checkin_{person_id}")
                if checkin == "yes":
                    member_attend.append(person_id)
                elif checkin == "no":
                    member_unattend.append(person_id)
            with transaction.atomic():
                member_list.select_for_update().filter(
                    person_id_id__in=member_attend).update(
                        status=Participant.AttendStatus.ATTENDED)
                member_list.select_for_update().filter(
                    person_id_id__in=member_unattend).update(
                        status=Participant.AttendStatus.UNATTENDED)
            # 修改成功之后根据src的不同返回不同的界面，1代表聚合页面，2代表活动主页
            if src == "course_center":
                return redirect(message_url(
                    succeed("修改签到信息成功。"), f"/showCourseActivity/"))
            else:
                return redirect(message_url(
                    succeed("修改签到信息成功。"), f"/viewActivity/{aid}"))

    bar_display = utils.get_sidebar_and_navbar(request.user,
                                               navbar_name="调整签到信息")
    member_list = member_list.select_related('person_id')
    render_context = dict(bar_display=bar_display, member_list=member_list)
    return render(request, "activity_checkinoffline.html", render_context)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def endActivity(request: HttpRequest):
    """
    之前被用为报销信息的聚合界面，现已将报销删去，留下总结图片的功能
    对审核老师进行了特判
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_auditor = False
    if user_type == UTYPE_PER:
        try:
            person = utils.get_person_or_org(request.user, user_type)
            is_auditor = person.is_teacher()
            assert is_auditor
        except:
            return redirect(message_url(wrong("请不要使用个人账号申请活动结项！")))

    if is_auditor:
        all_instances = {
            "undone": ActivitySummary.objects.filter(
                activity__examine_teacher=person,
                status=ActivitySummary.Status.WAITING).order_by("-time"),
            "done": ActivitySummary.objects.filter(
                activity__examine_teacher=person).exclude(
                status=ActivitySummary.Status.WAITING).order_by("-time")
        }

    else:
        all_instances = {
            "undone":   ActivitySummary.objects.filter(
                activity__organization_id__organization_id=request.user,
                status=ActivitySummary.Status.WAITING).order_by("-time"),
            "done":     ActivitySummary.objects.filter(
                activity__organization_id__organization_id=request.user
            ).exclude(status=ActivitySummary.Status.WAITING).order_by("-time")
        }

    # 前端使用
    all_instances = all_instances
    bar_display = utils.get_sidebar_and_navbar(request.user, "活动结项")
    return render(request, "activity_summary_show.html", locals())


# 新建+修改+取消+审核 报销信息
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@logger.secure_view()
def modifyEndActivity(request: HttpRequest):
    # return
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身

    # 前端使用量user_type，表示观察者是小组还是个人

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None
    # 根据是否有newid来判断是否是第一次
    apply_id = request.GET.get("apply_id", None)
    # 获取前端页面中可能存在的提示
    my_messages.transfer_message_context(request.GET, html_display)

    if apply_id is not None:  # 如果存在对应申请
        try:  # 尝试获取已经新建的apply
            application: ActivitySummary = ActivitySummary.objects.get(
                id=apply_id)
            auditor = application.activity.examine_teacher.person_id  # 审核老师
            if user_type == UTYPE_PER and auditor != request.user:
                html_display = utils.user_login_org(
                    request, application.get_org())
                if html_display['warn_code'] == 1:
                    return redirect(message_url(html_display))
                else:  # 成功
                    user_type = UTYPE_ORG
                    me = application.get_org()
                    request.user = me.get_user()

            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者被审核老师之一
            assert (application.get_org().get_user()
                    == request.user) or (auditor == request.user)
        except:  # 恶意跳转
            return redirect(message_url(wrong("您没有权限访问该网址！")))

        is_new_application = False  # 前端使用量, 表示是老申请还是新的

    else:  # 如果不存在id, 默认应该传入活动信息
        # 只有小组才有可能申请
        if user_type != UTYPE_ORG:
            return redirect(message_url(wrong("您没有权限访问该网址！")))

        is_new_application = True  # 新的申请

    # 这种写法是为了方便随时取消某个条件
    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在小组新建申请的时候才可能出现，对应位is_new_application为True
        接下来POST
    '''

    if user_type == UTYPE_ORG:
        # 未总结活动
        summary_act_ids = (
            ActivitySummary.objects.all().exclude(
                status=ActivitySummary.Status.CANCELED)  # 未被取消的
            .exclude(status=ActivitySummary.Status.REFUSED)  # 未被拒绝的
            .values_list("activity__id", flat=True))
        # 可以新建申请的活动
        activities = (
            Activity.objects.activated()  # 本学期的
            .filter(organization_id=me)  # 本部门小组的
            .filter(status=Activity.Status.END)  # 已结束的
            .exclude(id__in=summary_act_ids))  # 还没有报销的

        activities.len = len(activities)
    else:
        activities = None

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST" and request.POST.get("post_type") is not None:
        # 首先确定申请状态
        post_type = request.POST.get("post_type")
        feasible_post = [
            "new_submit", "modify_submit", "cancel_submit",
            "accept_submit", "refuse_submit"
        ]
        if post_type not in feasible_post:
            return redirect(message_url(wrong('申请状态异常！')))

        # 接下来确定访问的个人/小组是不是在做分内的事情
        if (user_type == UTYPE_PER and feasible_post.index(post_type) <= 2
            ) or (user_type == UTYPE_ORG
                  and feasible_post.index(post_type) >= 3):
            return redirect(message_url(wrong('您无权进行此操作，如有疑惑, 请联系管理员')))

        if (post_type != "new_submit") and not application.is_pending():
            return redirect(message_url(wrong("不可以修改状态不为申请中的申请")))

        if post_type in ["new_submit", "modify_submit"]:
            if post_type == "new_submit":
                # 检查活动
                try:
                    act_id = int(request.POST.get('activity_id'))
                    activity = Activity.objects.get(id=act_id)
                    assert activity in activities  # 防止篡改POST导致伪造
                except:
                    return redirect(message_url(wrong('找不到该活动，请检查活动总结的合法性！')))

            with transaction.atomic():
                if post_type == "new_submit":
                    # 新建activity summary
                    application: ActivitySummary = ActivitySummary.objects.create(
                        status=ActivitySummary.Status.WAITING,
                        activity=activity,
                    )
                # 活动总结图片
                summary_photos = request.FILES.getlist('summaryimages')
                photo_num = len(summary_photos)
                if photo_num == 1:
                    # 合法性检查
                    for image in summary_photos:
                        if utils.if_image(image) != 2:
                            return redirect(
                                message_url(wrong("上传的总结图片只支持图片格式！")))
                    application.image = summary_photos[0]
                    application.save()

                else:
                    return redirect(message_url(wrong('图片内容为空或有多张图片！'), request.path))

                if post_type == "new_submit":
                    context = succeed(
                        f'活动“{application.activity.title}”的申请已成功发送，请耐心等待{application.activity.examine_teacher.name}老师审批！'
                    )
                else:
                    context = succeed(
                        f'活动“{application.activity.title}”的申请已成功修改，请耐心等待{application.activity.examine_teacher.name}老师审批！'
                    )
                context["application_id"] = application.id

        elif post_type == "cancel_submit":
            if not application.is_pending():  # 如果不在pending状态, 可能是重复点击
                return redirect(message_url(wrong("该申请已经完成或被取消")))
            application.status = ActivitySummary.Status.CANCELED
            application.save()
            context = succeed(f"成功取消“{application.activity.title}”的活动总结申请!")
            context["application_id"] = application.id

        else:
            if not application.is_pending():
                return redirect(message_url(wrong("无法操作, 该申请已经完成或被取消!")))

            if post_type == "refuse_submit":
                # 修改申请状态
                application.status = ActivitySummary.Status.REFUSED
                application.save()
                context = succeed(
                    f'已成功拒绝活动“{application.activity.title}”的活动总结申请！')
                context["application_id"] = application.id
            elif post_type == "accept_submit":
                # 修改申请的状态
                application.status = ActivitySummary.Status.CONFIRMED
                old_image = application.image
                if not old_image is None:
                    ActivityPhoto.objects.create(
                        image=old_image,
                        activity=application.activity,
                        time=datetime.now(),
                        type=ActivityPhoto.PhotoType.SUMMARY)
                application.save()
                context = succeed(f'活动“{application.activity.title}”的总结申请已通过！')
                context["application_id"] = application.id

        # 为了保证稳定性，完成POST操作后同意全体回调函数，进入GET状态
        if application is None:
            return redirect(message_url(context, '/modifyEndActivity/'))
        else:
            return redirect(message_url(context, f'/modifyEndActivity/?apply_id={application.id}'))

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————
    '''
        小组：可能是新建、修改申请
        老师：可能是审核申请
    '''

    # (1) 是否允许修改表单
    # 小组写表格?
    allow_form_edit = True if (user_type == UTYPE_ORG) and (
        is_new_application or application.is_pending()) else False

    # 老师审核?
    allow_audit_submit = True if (user_type == UTYPE_PER) and (
        not is_new_application) and (application.is_pending()) else False

    # 用于前端展示：如果是新申请，申请人即“me”，否则从application获取。
    apply_person = me if is_new_application else application.get_org()
    # 申请人头像
    app_avatar_path = apply_person.get_user_ava()

    # 活动总结图片
    summary_photo = application.image if application is not None else None
    summary_photo_exist = True if summary_photo is not None else False
    # 元培学院
    our_college = Organization.objects.get(
        oname="元培学院") if allow_audit_submit else None
    # 审核老师
    examine_teacher = application.activity.examine_teacher if application is not None else None
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="活动总结详情")

    return render(request, "modify_activity_summary.html", locals())
