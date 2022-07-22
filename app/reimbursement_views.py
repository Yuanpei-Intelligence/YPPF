from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    Reimbursement,
    ReimbursementPhoto,
)
from app.reimbursement_utils import update_reimb_application
from app.comment_utils import addComment, showComment
from app.notification_utils import make_notification

__all__ = [
    'endActivity', 'modifyEndActivity',
]

@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='reimbursement_views[endActivity]', record_user=True)
def endActivity(request: HttpRequest):
    """
    报销信息的聚合界面
    对审核老师进行了特判
    """
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_auditor = False
    if user_type == "Person":
        try:
            person = utils.get_person_or_org(request.user, user_type)
            is_auditor = person.is_teacher()
        except:
            pass
        if not is_auditor:
            html_display["warn_code"] = 1
            html_display["warn_message"] = "请不要使用个人账号申请活动结项！"
            return redirect(
                        "/welcome/"
                        + "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]
                        )
                    )

    if is_auditor:
        all_instances = {
            "undone": Reimbursement.objects.filter(examine_teacher=person, status = Reimbursement.ReimburseStatus.WAITING),
            "done": Reimbursement.objects.filter(examine_teacher=person).exclude(status = Reimbursement.ReimburseStatus.WAITING)
        }

    else:
        all_instances = {
            "undone":   Reimbursement.objects.filter(pos=request.user, status = Reimbursement.ReimburseStatus.WAITING),
            "done":     Reimbursement.objects.filter(pos=request.user).exclude(status = Reimbursement.ReimburseStatus.WAITING)
        }

    all_instances = {key:value.order_by("-modify_time", "-time") for key, value in all_instances.items()}
    #shown_instances = shown_instances.order_by("-modify_time", "-time")
    bar_display = utils.get_sidebar_and_navbar(request.user, "活动结项")
    return render(request, "reimbursement_show.html", locals())


# 新建+修改+取消+审核 报销信息
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='reimbursement_views[modifyEndActivity]', record_user=True)
def modifyEndActivity(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user)  # 获取自身

    # 前端使用量user_type，表示观察者是小组还是个人

    # ———————————————— 读取可能存在的申请 为POST和GET做准备 ————————————————

    # 设置application为None, 如果非None则自动覆盖
    application = None
    # 根据是否有newid来判断是否是第一次
    reimb_id = request.GET.get("reimb_id", None)
    # 获取前端页面中可能存在的提示
    try:
        if request.GET.get("warn_code", None) is not None:
            html_display["warn_code"] = int(request.GET.get("warn_code"))
            html_display["warn_message"] = request.GET.get("warn_message")
    except:
        pass

    if reimb_id is not None:  # 如果存在对应报销
        try:  # 尝试获取已经新建的Reimbursement
            application = Reimbursement.objects.get(id=reimb_id)
            auditor = application.examine_teacher.person_id   # 审核老师
            if user_type == "Person" and auditor!=request.user:
                html_display=utils.user_login_org(request, application.pos.organization)
                if html_display['warn_code']==1:
                    return redirect(
                        "/welcome/"
                        + "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]
                        )
                    )
                else: #成功
                    user_type = "Organization"
                    request.user = application.pos
                    me = application.pos.organization

            # 接下来检查是否有权限check这个条目
            # 至少应该是申请人或者被审核老师之一
            assert (application.pos == request.user) or (auditor == request.user)
        except:  # 恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有权限访问该网址！"
            return redirect(
                        "/welcome/"
                        + "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]
                        )
                    )
        is_new_application = False  # 前端使用量, 表示是老申请还是新的

    else:  # 如果不存在id, 默认应该传入活动信息
        #只有小组才有可能报销
        try:
            assert user_type == "Organization"
        except:  # 恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有权限访问该网址！"
            return redirect(
                        "/welcome/"
                        + "?warn_code=1&warn_message={warn_message}".format(
                            warn_message=html_display["warn_message"]
                        )
                    )
        is_new_application = True  # 新的申请

        # 这种写法是为了方便随时取消某个条件
    '''
        至此，如果是新申请那么application为None，否则为对应申请
        application = None只有在小组新建申请的时候才可能出现，对应位is_new_application为True
        接下来POST
    '''

    # ———————— Post操作，分为申请变更以及添加评论   ————————

    if request.method == "POST":
        # 如果是状态变更
        if request.POST.get("post_type", None) is not None:

            # 主要操作函数，更新申请状态
            context = update_reimb_application(application, me, user_type, request)

            if context["warn_code"] == 2:  # 成功修改申请
                # 回传id 防止意外的锁操作
                application = Reimbursement.objects.get(id=context["application_id"])
                is_new_application = False  # 状态变更

                # 处理通知相关的操作，并根据情况发送微信
                # 默认需要成功, 失败也不是用户的问题，直接给管理员报错
                #小组名字
                org_name = application.pos.organization.oname
                #活动标题
                act_title = application.related_activity.title
                # 准备创建notification需要的构件：发送内容
                content = {
                    'new_submit': f'{org_name}发起活动{act_title}的经费申请，请审核~',
                    'modify_submit': f'{org_name}修改了活动{act_title}的经费申请，请审核~',
                    'cancel_submit': f'{org_name}取消了活动{act_title}的经费申请。',
                    'accept_submit': f'恭喜，您申请的经费申请：{act_title}，审核已通过！已扣除元气值{application.amount}',
                    'refuse_submit': f'抱歉，您申请的经费申请：{act_title}，审核未通过！',
                }
                #通知的接收者
                auditor = application.examine_teacher.person_id
                if user_type == "Organization":
                    receiver = auditor
                else:
                    receiver = application.pos
                #创建通知
                make_notification(application, request, content, receiver)
            elif context["warn_code"] != 1:  # 没有返回操作提示
                raise NotImplementedError("处理经费申请中出现未预见状态，请联系管理员处理！")


        else:  # 如果是新增评论
            # 权限检查
            allow_comment = True if (not is_new_application) and (
                application.is_pending()) else False
            if not allow_comment:  # 存在不合法的操作
                return redirect(message_url(wrong('存在不合法操作,请与管理员联系!')))
            #通知的接收者
            auditor = application.examine_teacher.person_id
            if user_type == "Organization":
                receiver = auditor
            else:
                receiver = application.pos
            context = addComment(request, application, receiver)

        # 为了保证稳定性，完成POST操作后同意全体回调函数，进入GET状态
        if application is None:
            return redirect(message_url(context, '/modifyEndActivity/'))
        else:
            return redirect(message_url(context, f'/modifyEndActivity/?reimb_id={application.id}'))

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————
    '''
        小组：可能是新建、修改申请
        老师：可能是审核申请
    '''

    # (1) 是否允许修改表单
    # 小组写表格?
    allow_form_edit = True if (user_type == "Organization") and (
            is_new_application or application.is_pending()) else False
    # 老师审核?
    allow_audit_submit = True if (user_type == "Person") and (not is_new_application) and (
        application.is_pending()) else False

    # 是否可以评论
    commentable = True if (not is_new_application) and (application.is_pending()) \
        else False
    comments = showComment(application) if application is not None else None
    # 用于前端展示：如果是新申请，申请人即“me”，否则从application获取。
    apply_person = me if is_new_application else utils.get_person_or_org(application.pos)
    #申请人头像
    app_avatar_path = apply_person.get_user_ava()

    # 未报销活动
    activities = utils.get_unreimb_activity(apply_person)

    #活动总结图片
    summary_photos = application.reimbphotos.filter(
        type=ReimbursementPhoto.PhotoType.SUMMARY
    ) if application is not None else None
    summary_photo_len = len(summary_photos) if summary_photos is not None else 0
    #元培学院
    our_college = Organization.objects.get(oname="元培学院") if allow_audit_submit else None
    #审核老师
    available_teachers = NaturalPerson.objects.teachers()
    examine_teacher = application.examine_teacher if application is not None else None
    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="经费申请详情")
    return render(request, "modify_reimbursement.html", locals())

