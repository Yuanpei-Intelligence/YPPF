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
from app.activity_utils import (
    ActivityException,
    hash_coder,
    create_activity,
    modify_activity,
    accept_activity,
    reject_activity,
    applyActivity,
    cancel_activity,
    withdraw_activity,
    get_activity_QRcode,
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
    'viewActivity', 'getActivityInfo', 'checkinActivity',
    'addActivity', 'showActivity', 'examineActivity',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[viewActivity]', record_user=True)
def viewActivity(request, aid=None):
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
    aprice = request.POST["aprice"]  # 活动价格
    capacity = request.POST["capacity"]  # 活动举办的容量
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
                    html_display["warn_code"] = 2
                    html_display["warn_message"] = "成功取消活动。"
            except ActivityException as e:
                html_display["warn_code"] = 1
                html_display["warn_message"] = str(e)
            except Exception as e:
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT

        elif option == "edit":
            if (
                    activity.status == Activity.Status.APPLYING
                    or activity.status == Activity.Status.REVIEWING
            ):
                return redirect(f"/editActivity/{aid}")
            if activity.status == Activity.Status.WAITING:
                if activity.start + timedelta(hours=1) < datetime.now():
                    return redirect(f"/editActivity/{aid}")
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"距离活动开始前1小时内将不再允许修改活动。如确有雨天等意外情况，请及时取消活动，收取的元气值将会退还。"
            else:
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"活动状态为{activity.status}, 不能修改。"

        elif option == "apply":
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=int(aid))
                    if activity.status != Activity.Status.APPLYING:
                        return redirect(message_url(wrong('活动不在报名状态!'), request.path))
                    applyActivity(request, activity)
                    if activity.bidding:
                        html_display["warn_message"] = f"活动申请中，请等待报名结果。"
                    else:
                        html_display["warn_message"] = f"报名成功。"
                    html_display["warn_code"] = 2
            except ActivityException as e:
                html_display["warn_code"] = 1
                html_display["warn_message"] = str(e)
            except Exception as e:
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT


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
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT

        elif option == "payment":
            if activity.status != Activity.Status.END:
                return redirect(message_url(wrong('活动尚未结束!'), request.path))
            if not ownership:
                return redirect(message_url(wrong('您没有申请活动结项的权限!'), request.path))
            try:
                re = Reimbursement.objects.get(related_activity=activity)
                return redirect(f"/modifyEndActivity/?reimb_id={re.id}")
            except:
                return redirect(f"/modifyEndActivity/")
        elif option == "sign" or option == "enroll": #下载活动签到信息或者报名信息
            if not ownership:
                return redirect(message_url(wrong('没有下载权限!'), request.path))
            return utils.export_activity(activity,option)
        elif option == "cancelInformShare":
            me.inform_share = False
            me.save()
            return redirect("/welcome/")
        else:
            return redirect(message_url(wrong('无效的请求!'), request.path))
        
    elif request.method == "GET":
        warn_code = request.GET.get("warn_code")
        warn_msg = request.GET.get("warn_message")
        if warn_code and warn_msg:
            if warn_code != "1" and warn_code != "2":
                return redirect(message_url(wrong('非法的状态码，请勿篡改URL!'), request.path))
            html_display["warn_code"] = int(warn_code)
            html_display["warn_message"] = warn_msg


    # 下面这些都是展示前端页面要用的
    title = activity.title
    org_name = org.oname
    org_avatar_path = org.get_user_ava()
    org_type = OrganizationType.objects.get(otype_id=org.otype_id).otype_name
    start_month = activity.start.month
    start_date = activity.start.day
    duration = activity.end - activity.start
    prepare_times = Activity.EndBeforeHours.prepare_times
    apply_deadline = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    introduction = activity.introduction
    show_url = True # 前端使用量
    aURL = activity.URL
    if (aURL is None) or (aURL == ""):
        show_url = False
    bidding = activity.bidding
    price = activity.YQPoint
    from_student = activity.source == Activity.YQPointSource.STUDENT
    current_participants = activity.current_participants
    status = activity.status
    capacity = activity.capacity
    if capacity == -1 or capacity == 10000:
        capacity = "INF"
    if activity.source == Activity.YQPointSource.COLLEGE:
        price = 0
    if activity.bidding:
        apply_manner = "抽签模式"
    else:
        apply_manner = "先到先得"
    # person 表示是否是个人而非小组
    person = False
    if user_type == "Person":
        """
        老师能否报名活动？
        if me.identity == NaturalPerson.Identity.STUDENT:
            person = True
        """
        person = True
        try:
            participant = Participant.objects.get(activity_id=activity, person_id=me.id)
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

    if activity.inner and user_type == "Person":
        position = Position.objects.activated().filter(person=me, org=activity.organization_id)
        if len(position) == 0:
            not_inner = True

    if ownership and need_checkin:
        aQRcode = get_activity_QRcode(activity)

    # 活动宣传图片 ( 一定存在 )
    photo = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
    firstpic = str(photo.image)
    if firstpic[0] == 'a': # 不是static静态文件夹里的文件，而是上传到media/activity的图片
        firstpic = MEDIA_URL + firstpic

    # 总结图片，不一定存在
    summary_photo_exists = False
    if activity.status == Activity.Status.END:
        try:
            summary_photos = activity.photos.filter(type=ActivityPhoto.PhotoType.SUMMARY)
            summary_photo_exists = True
        except Exception as e:
            pass
    
    # 参与者, 无论报名是否通过
    participants = Participant.objects.filter(Q(activity_id=activity),
        Q(status=Participant.AttendStatus.APPLYING) | Q(status=Participant.AttendStatus.APLLYSUCCESS) | Q(status=Participant.AttendStatus.ATTENDED) | Q(status=Participant.AttendStatus.UNATTENDED))
    #participants_ava = [utils.get_user_ava(participant, "Person") for participant in participants.values("person_id")] or None
    people_list = NaturalPerson.objects.activated().filter(id__in = participants.values("person_id"))


    # 新版侧边栏，顶栏等的呈现，采用bar_display，必须放在render前最后一步，但这里render太多了
    # TODO: 整理好代码结构，在最后统一返回
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="活动信息", title_name=title)
    # 补充一些呈现信息
    # bar_display["title_name"] = "活动信息"
    # bar_display["navbar_name"] = "活动信息"

    # 浏览次数，必须在render之前
    # 为了防止发生错误的存储，让数据库直接更新浏览次数，并且不再显示包含本次浏览的数据
    Activity.objects.filter(id=activity.id).update(visit_times=F('visit_times')+1)
    # activity.visit_times += 1
    # activity.save()
    return render(request, "activity_info.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[getActivityInfo]', record_user=True)
def getActivityInfo(request):
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
    try:
        activity = Activity.objects.get(id=activity_id)
    except:
        html_display["warn_code"] = 1
        html_display["warn_message"] = f"活动{activity_id}不存在"
        return render(request, "某个页面.html", locals())

    # check organization existance and ownership to activity
    organization = utils.get_person_or_org(request.user, "organization")
    if activity.organization_id != organization:
        html_display["warn_code"] = 1
        html_display["warn_message"] = f"{organization}不是活动的组织者"
        return render(request, "某个页面.html", locals())

    info_type = request.GET.get("infotype", None)
    if info_type == "sign":  # get registration information
        # make sure registration is over
        if activity.status == Activity.Status.REVIEWING:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "活动正在审核"
            return render(request, "某个页面.html", locals())

        elif activity.status == Activity.Status.CANCELED:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "活动已取消"
            return render(request, "某个页面.html", locals())

        elif activity.status == Activity.Status.APPLYING:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "报名尚未截止"
            return render(request, "某个页面.html", locals())

        else:
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
                if not field in allowed_fields:
                    html_display["warn_code"] = 1
                    html_display["warn_message"] = f"不允许的字段名{field}"
                    return render(request, "某个页面.html", locals())

            filename = f"{activity_id}-{info_type}-{output}"
            content = map(
                lambda paticipant: map(lambda key: paticipant[key], fields),
                participants,
            )

            format = request.GET.get("format", "csv")
            if format == "csv":
                buffer = io.StringIO()
                csv.writer(buffer).writerows(content), buffer.seek(0)
                response = HttpResponse(buffer, content_type="text/csv")
                response["Content-Disposition"] = f"attachment; filename={filename}.csv"
                return response  # downloadable

            elif format == "excel":
                return HttpResponse(".xls Not Implemented")

            else:
                html_display["warn_code"] = 1
                html_display["warn_message"] = f"不支持的格式{format}"
                return render(request, "某个页面.html", locals())

    elif info_type == "qrcode":
        # checkin begins 1 hour ahead
        if datetime.now() < activity.start - timedelta(hours=1):
            html_display["warn_code"] = 1
            html_display["warn_message"] = "签到失败：签到未开始"
            return render(request, "某个页面.html", locals())

        else:
            checkin_url = f"/checkinActivity?activityid={activity.id}"
            origin_url = request.scheme + "://" + request.META["HTTP_HOST"]
            checkin_url = urllib.parse.urljoin(origin_url, checkin_url)  # require full path

            buffer = io.BytesIO()
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(checkin_url), qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(buffer, "jpeg"), buffer.seek(0)
            response = HttpResponse(buffer, content_type="img/jpeg")
            return response

    else:
        html_display["warn_code"] = 1
        html_display["warn_message"] = f"不支持的信息{info_type}"
        return render(request, "某个页面.html", locals())

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[checkinActivity]', record_user=True)
def checkinActivity(request, aid=None):
    valid, user_type, html_display = utils.check_user_type(request.user)
    if user_type != "Person":
        return redirect(message_url(wrong('签到失败：请使用个人账号签到')))
    try:
        np = get_person_or_org(request.user, user_type)
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        varifier = request.GET["auth"]
    except:
        return redirect(message_url(wrong('签到失败!')))
    if varifier != hash_coder.encode(str(aid)):
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
@log.except_captured(source='views[checkinActivity]', record_user=True)
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
@log.except_captured(EXCEPT_REDIRECT, source='views[addActivity]', record_user=True)
def addActivity(request, aid=None):
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
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type) # 这里的me应该为小组账户
        if aid is None:
            if user_type != "Organization":
                return redirect(message_url(wrong('小组账号才能添加活动!')))
            if me.oname == YQP_ONAME:
                return redirect("/showActivity")
            edit = False
        else:
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
            edit = True
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 处理 POST 请求
    # 在这个界面，不会返回render，而是直接跳转到viewactivity，可以不设计bar_display
    if request.method == "POST" and request.POST:

        if not edit:
            try:
                with transaction.atomic():
                    aid, created = create_activity(request)
                    if not created:
                        return redirect(message_url(
                            succeed('存在信息相同的活动，已为您自动跳转!'),
                            f'/viewActivity/{aid}'))
                    return redirect(f"/editActivity/{aid}")
            except Exception as e:
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT

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
            context = addComment(request, activity, activity.examine_teacher.person_id)
            # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
            assert context["warn_code"] == 2, context["warn_message"]
            # 成功后重新加载界面
            html_display["warn_msg"] = "评论成功。"
            html_display["warn_code"] = 2
            # return redirect(f"/editActivity/{aid}")
        else:
            try:
                # 只能修改自己的活动
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(id=aid)
                    org = get_person_or_org(request.user, "Organization")
                    assert activity.organization_id == org
                    modify_activity(request, activity)
                html_display["warn_msg"] = "修改成功。"
                html_display["warn_code"] = 2
            except ActivityException as e:
                html_display["warn_msg"] = str(e)
                html_display["warn_code"] = 1
                # return redirect(f"/viewActivity/{activity.id}")
            except Exception as e:
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT

    # 下面的操作基本如无特殊说明，都是准备前端使用量
    defaultpics = [{"src": f"/static/assets/img/announcepics/{i+1}.JPG", "id": f"picture{i+1}"} for i in range(5)]
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava() 
    try:
        tid = Activity.objects.filter(organization_id=me).last().id
    except AttributeError:
        # 说明这个组织之前没有组织过活动
        tid = None
    use_template = False
    if request.method == "GET" and request.GET.get("template"):
        use_template = True
        template_id = int(request.GET["template"])
        activity = Activity.objects.get(id=template_id)
    if not edit and not use_template:
        available_teachers = NaturalPerson.objects.teachers()
    else:
        try:
            org = get_person_or_org(request.user, "Organization")

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
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT

        # 决定状态的变量
        # None/edit/examine ( 小组申请活动/小组编辑/老师审查 )
        # full_editable/accepted/None ( 小组编辑活动：除审查老师外全可修改/部分可修改/全部不可改 )
        #        full_editable 为 true 时，accepted 也为 true
        # commentable ( 是否可以评论 )

        # 下面是前端展示的变量

        title = utils.escape_for_templates(activity.title)
        budget = activity.budget
        location = utils.escape_for_templates(activity.location)
        apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
        # apply_end_for_js = activity.apply_end.strftime("%Y-%m-%d %H:%M")
        start = activity.start.strftime("%Y-%m-%d %H:%M")
        end = activity.end.strftime("%Y-%m-%d %H:%M")
        introduction = escape_for_templates(activity.introduction)
        url = utils.escape_for_templates(activity.URL)

        endbefore = activity.endbefore
        bidding = activity.bidding
        amount = activity.YQPoint
        signscheme = "先到先得"
        if bidding:
            signscheme = "抽签模式"
        capacity = activity.capacity
        yq_source = "向学生收取"
        if activity.source == Activity.YQPointSource.COLLEGE:
            yq_source = "向学院申请"
        no_limit = False
        if capacity == 10000:
            no_limit = True
        examine_teacher = activity.examine_teacher.name
        status = activity.status
        available_teachers = NaturalPerson.objects.filter(identity=NaturalPerson.Identity.TEACHER)
        need_checkin = activity.need_checkin
        inner = activity.inner
        apply_reason = utils.escape_for_templates(activity.apply_reason)
        if not use_template:
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
    if not edit:
        bar_display = utils.get_sidebar_and_navbar(request.user, "活动发起")
    else:
        bar_display = utils.get_sidebar_and_navbar(request.user, "修改活动")

    return render(request, "activity_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[showActivity]', record_user=True)
def showActivity(request):
    """
    活动信息的聚合界面
    只有老师和小组才能看到，老师看到检查者是自己的，小组看到发起方是自己的
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身
    is_teacher = False #该变量同时用于前端
    if user_type == "Person":
        try:
            person = utils.get_person_or_org(request.user, user_type)
            if person.identity == NaturalPerson.Identity.TEACHER :
                is_teacher = True
        except:
            pass
        if not is_teacher:
            html_display["warn_code"] = 1

            html_display["warn_message"] = "学生账号不能进入活动立项页面！"

            return redirect(
                        "/welcome/"
                        + "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]
                        )
                    )
    if is_teacher:
        all_instances = {
            "undone":   Activity.objects.activated(only_displayable=False).filter(examine_teacher = me.id, valid = False),
            "done":     Activity.objects.activated(only_displayable=False).filter(examine_teacher = me.id, valid = True)
        }
    else:
        all_instances = {
            "undone":   Activity.objects.activated(only_displayable=False).filter(organization_id = me.id, valid = False),
            "done":     Activity.objects.activated(only_displayable=False).filter(organization_id = me.id, valid = True)
        }

    all_instances = {key:value.order_by("-modify_time", "-time") for key,value in all_instances.items()}
    bar_display = utils.get_sidebar_and_navbar(request.user, "活动立项")

    # 前端不允许元气值中心创建活动
    if user_type == "Organization" and me.oname == YQP_ONAME:
        YQPoint_Source_Org = True

    return render(request, "activity_show.html", locals())


@login_required(redirect_field_name="origin")
@log.except_captured(source='views[examineActivity]', record_user=True)
def examineActivity(request, aid):
    valid, user_type, html_display = utils.check_user_type(request.user)
    try:
        assert valid
        assert user_type == "Person"
        me = utils.get_person_or_org(request.user)
        activity = Activity.objects.get(id=int(aid))
        assert activity.examine_teacher == me
    except:
        return redirect("/welcome/")

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
            try:
                context = addComment(request, activity, activity.organization_id.organization_id)
                # 评论内容不为空，上传文件类型为图片会在前端检查，这里有错直接跳转
                assert context["warn_code"] == 2
                html_display["warn_msg"] = "评论成功。"
                html_display["warn_code"] = 2
            except Exception as e:
                return EXCEPT_REDIRECT

        elif request.POST.get("review_accepted"):
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(
                        id=int(aid)
                    )
                    accept_activity(request, activity)
                html_display["warn_msg"] = "活动已通过审核。"
                html_display["warn_code"] = 2
            except Exception as e:
                return EXCEPT_REDIRECT
        else:
            try:
                with transaction.atomic():
                    activity = Activity.objects.select_for_update().get(
                        id=int(aid)
                    )
                    reject_activity(request, activity)
                html_display["warn_msg"] = "活动已被拒绝。"
                html_display["warn_code"] = 2
            except Exception as e:
                return EXCEPT_REDIRECT


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
    budget = activity.budget
    location = utils.escape_for_templates(activity.location)
    apply_end = activity.apply_end.strftime("%Y-%m-%d %H:%M")
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
    introduction = escape_for_templates(activity.introduction)

    url = utils.escape_for_templates(activity.URL)
    endbefore = activity.endbefore
    bidding = activity.bidding
    amount = activity.YQPoint
    signscheme = "先到先得"
    if bidding:
        signscheme = "投点参与"
    capacity = activity.capacity
    yq_source = "向学生收取"
    if activity.source == Activity.YQPointSource.COLLEGE:
        yq_source = "向学院申请"
    no_limit = False
    if capacity == 10000:
        no_limit = True
    examine_teacher = activity.examine_teacher.name
    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    # html_display["app_avatar_path"] = utils.get_user_ava(activity.organization_id,"Organization")h
    html_display["app_avatar_path"] = activity.organization_id.get_user_ava()
    html_display["applicant_name"] = activity.organization_id.oname
    bar_display = utils.get_sidebar_and_navbar(request.user)
    status = activity.status
    comments = showComment(activity)

    examine_pic = activity.photos.get(type=ActivityPhoto.PhotoType.ANNOUNCE)
    if str(examine_pic.image)[0] == 'a': # 不是static静态文件夹里的文件，而是上传到media/activity的图片
        examine_pic.image = MEDIA_URL + str(examine_pic.image)
    intro_pic = examine_pic.image

    need_checkin = activity.need_checkin
    apply_reason = utils.escape_for_templates(activity.apply_reason)

    bar_display = utils.get_sidebar_and_navbar(request.user, "活动审核")
    # bar_display["title_name"] = "审查活动"
    # bar_display["narbar_name"] = "审查活动"
    return render(request, "activity_add.html", locals())
    