from app.views_dependency import *
from app.models import (
    Organization,
    OrganizationType,
    Notification,
    Feedback,
    FeedbackType,
)
from app.utils import (
    get_person_or_org,
)
from django.db.models import Q
from django.db import transaction
from app.feedback_utils import (
    examine_notification,
    update_feedback,
    make_relevant_notification,
    inform_notification,
)
from app.comment_utils import addComment, showComment


__all__ = [
    'feedbackWelcome',
    'viewFeedback',
    'modifyFeedback',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='feedback_views[viewFeedback]', record_user=True)
def viewFeedback(request: HttpRequest, fid):
    try:
        # 查找fid对应的反馈条目
        fid = int(fid)
        feedback: Feedback = Feedback.objects.get(id=fid)
    except:
        return redirect(message_url(wrong("反馈不存在！"), '/feedback/'))

    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user, user_type)

    # 获取前端页面中可能存在的提示
    my_messages.transfer_message_context(request.GET, html_display)

    # 添加评论和修改活动状态
    if request.method == "POST" and request.POST:
        # 添加评论
        if request.POST.get("comment_submit"):
            # 只有未完成反馈可以发送评论
            if feedback.solve_status not in [
                Feedback.SolveStatus.SOLVING,
                Feedback.SolveStatus.UNMARKED,
                ]:
                return redirect(message_url(wrong("已结束的反馈不能评论！"), request.path))
            anonymous = False
            # 确定通知消息的发送人，互相发送给对方
            if user_type == UTYPE_PER and feedback.person == me:
                receiver = feedback.org.organization_id
                anonymous = True
            elif user_type == UTYPE_ORG and feedback.org == me:
                receiver = feedback.person.person_id
            # 老师可以评论，给双方发送通知消息
            elif user_type == UTYPE_PER and me.is_teacher():
                receiver = [
                    feedback.org.organization_id,
                    feedback.person.person_id,
                ]
            # 其他人没有评论权限
            else:
                return redirect(message_url(wrong("没有评论权限！"), request.path))
            # 满足以上条件后可以添加评论
            addComment(request, feedback, receiver,
                       anonymous=anonymous,
                       notification_title=Notification.Title.FEEDBACK_INFORM)
            return redirect(message_url(succeed("成功添加1条评论！"), request.path))

        # 以下为调整反馈的状态
        public = request.POST.get("public_status")
        read = request.POST.get("read_status", "unread")
        solve = request.POST.get("solve_status", "solving")
        # 成功反馈信息
        succeed_message = []
        # 一、修改已读状态
        # 只有已读条目才可以进行后续的修改
        if feedback.read_status == Feedback.ReadStatus.UNREAD:
            # 只有组织可以修改已读状态
            if user_type == UTYPE_ORG and feedback.org == me:
                if read != "read":
                    return redirect(message_url(wrong("必须先设置为已读！"), request.path))
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    if read == "read":
                        feedback.read_status = Feedback.ReadStatus.READ
                        feedback.solve_status = Feedback.SolveStatus.SOLVING
                    # 已读条目不允许恢复为未读
                    # elif read == "unread":
                    #     feedback.read_status = Feedback.ReadStatus.UNREAD
                    feedback.save()
                    succeed_message.append("成功修改状态为【已读】！")
                    inform_notification(me, feedback.person,
                                        f"您的反馈[{feedback.title}]已知悉。",
                                        feedback,
                                        important=True)
            # 其他人没有标记已读权限
            else:
                return redirect(message_url(wrong("没有修改已读状态的权限！"), request.path))


        # 二、修改解决状态
        feedback = Feedback.objects.get(id=fid)
        # 只有已读条目才可以修改解决状态；只有已解决/无法解决的条目才可以修改后续状态
        if feedback.solve_status == Feedback.SolveStatus.SOLVING:
            # 只有组织可以修改解决状态
            if user_type == UTYPE_ORG and feedback.org == me:
                # 只有已读条目才可以修改解决状态：
                if feedback.read_status != Feedback.ReadStatus.READ:
                    return redirect(message_url(wrong("只有已读反馈可以修改解决状态！"), request.path))
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    # 修改为已解决
                    if solve == "solve":
                        feedback.solve_status = Feedback.SolveStatus.SOLVED
                    # 修改为无法解决
                    elif solve == "unsolvable":
                        feedback.solve_status = Feedback.SolveStatus.UNSOLVABLE
                    feedback.save()
                    if solve != "solving":
                        succeed_message.append(
                            f"成功修改解决状态为【{feedback.get_solve_status_display()}】")
                        inform_notification(
                            me, feedback.person,
                            f"您的反馈[{feedback.title}]已修改状态为"
                            +f"【{feedback.get_solve_status_display()}】。",
                            feedback, important=True,
                            )
            # 其他人没有修改解决状态权限
            # else:
            #     return redirect(message_url(wrong("没有修改解决状态的权限！"), request.path))

        # 三、公开反馈信息
        feedback = Feedback.objects.get(id=fid)
        if public == "public":
            # 组织选择公开反馈
            if user_type == UTYPE_ORG and feedback.org == me:
                # 只有完成的反馈可以公开。另外组织已公开的反馈必然已完成
                if feedback.solve_status in [
                    Feedback.SolveStatus.SOLVING,
                    Feedback.SolveStatus.UNMARKED,
                    ]:
                    return redirect(message_url(
                        wrong("只有已解决/无法解决的反馈才可以公开"), request.path))
                # 若老师不予公开，则不允许修改
                if feedback.public_status == Feedback.PublicStatus.FORCE_PRIVATE:
                    return redirect(message_url(
                        wrong("审核教师已设置不予公开！"), request.path))
                # 若个人不公开
                if feedback.publisher_public == False:
                    return redirect(message_url(
                        wrong("根据反馈人的设置，你无法公开这一反馈结果。"
                            + "如果以后遇到希望公开的反馈，请在状态为【解决中】时提醒用户调整状态为【公开】！"),
                        request.path))
                # 若老师没有不予公开，则修改组织公开状态
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.org_public = True
                    feedback.save()
                    succeed_message.append("成功修改组织公开状态为【公开】！通过学院审核后，该反馈将向所有人公开。")
                    inform_notification(me, feedback.person,
                                        f"已申请公开您的反馈[{feedback.title}]，等待老师审核。",
                                        feedback)
                # 此时若发布者也选择公开，则向老师发送通知消息，提醒审核
                if feedback.publisher_public:
                    examine_notification(feedback)

            # 发布者（个人）选择公开反馈
            elif user_type == UTYPE_PER and feedback.person == me:
                # 若老师不予公开，则不允许修改
                if feedback.public_status == Feedback.PublicStatus.FORCE_PRIVATE:
                    return redirect(message_url(wrong("审核教师已设置不予公开！"), request.path))
                # 若老师没有不予公开，则修改发布者公开状态
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.publisher_public = True
                    feedback.save()
                    succeed_message.append("成功修改个人公开状态为【公开】！待小组公开并通过学院审核后，该反馈将向所有人公开。")
                # 此时若组织也选择公开，则向老师发送通知消息，提醒审核
                if feedback.org_public:
                    examine_notification(feedback)

            # 教师选择公开反馈
            elif (
                user_type == UTYPE_PER and me.is_teacher()
            ):
                # 若组织或发布者有不公开的意愿，则教师不能公开
                if (feedback.publisher_public != True or feedback.org_public != True):
                    return redirect(message_url(wrong("小组/个人没有选择公开反馈！"), request.path))
                # 教师可以公开组织和发布者均公开的反馈
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.public_status = Feedback.PublicStatus.PUBLIC
                    feedback.save()
                    succeed_message.append("成功修改反馈公开状态为【公开】！所有学生都有访问权限。")
                    inform_notification(me, feedback.person, f"已公开您的反馈[{feedback.title}]。", feedback, anonymous=False)
                    inform_notification(me, feedback.org, f"已公开您处理的反馈[{feedback.title}]。", feedback, anonymous=False)
            # 其他人没有公开反馈权限
            else:
                return redirect(message_url(wrong("没有公开该反馈的权限！"), request.path))
        else:
            if user_type == UTYPE_ORG and feedback.org == me:
                # 修改组织公开状态
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.org_public = False
                    if feedback.public_status == Feedback.PublicStatus.PUBLIC:
                        feedback.public_status = Feedback.PublicStatus.PRIVATE
                    feedback.save()
                    succeed_message.append("成功修改组织公开状态为【不公开】！")
                    inform_notification(me, feedback.person,
                                        f"组织设置您的反馈[{feedback.title}]状态为【不公开】。",
                                        feedback)
        # 四、隐藏反馈信息
        feedback = Feedback.objects.get(id=fid)
        if public == "private":
            # 小组和个人公开反馈后，暂不允许恢复隐藏状态
            # 组织选择隐藏反馈
            if user_type == UTYPE_ORG and feedback.org == me:
                pass
                """ # 小组已公开不允许恢复隐藏，因此不采取任何操作
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.org_public = False
                    # 此时若老师没有不予公开，则隐藏反馈状态
                    if feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE:
                        feedback.public_status = Feedback.PublicStatus.PRIVATE
                    feedback.save()
                """
            # 发布者（个人）选择隐藏反馈
            elif user_type == UTYPE_PER and feedback.person == me:
                pass
                """ # 发布者已公开不允许恢复隐藏，因此不采取任何操作
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.publisher_public = False
                    # 此时若老师没有不予公开，则隐藏反馈状态
                    if feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE:
                        feedback.public_status = Feedback.PublicStatus.PRIVATE
                    feedback.save()
                """
            # 教师选择隐藏反馈
            elif (
                user_type == UTYPE_PER and me.is_teacher()
            ):
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    # 教师为不予公开
                    feedback.public_status = Feedback.PublicStatus.FORCE_PRIVATE
                    feedback.save()
                    succeed_message.append("成功修改反馈状态为【不予公开】，除发布者和小组外均无访问权限。")
                    inform_notification(me, feedback.person, f"暂不公开您的反馈[{feedback.title}]。", feedback, anonymous=False)
                    inform_notification(me, feedback.org, f"暂不公开您处理的反馈[{feedback.title}]。", feedback, anonymous=False)
            # 其他人没有隐藏反馈权限
            else:
                return redirect(message_url(wrong("没有隐藏该反馈的权限！"), request.path))
        """撤销反馈修改为聚合页面进行，这里暂时不用
        # 五、撤销反馈
        if request.POST.get("post_type") == "cancel":
            # 只有发布者可以撤销反馈
            if feedback.person == me:
                # 已完成的反馈不允许撤回
                if feedback.solve_status != Feedback.SolveStatus.SOLVING:
                    return redirect(message_url(wrong("只有未解决的反馈才可以撤回"), request.path))
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.issue_status = Feedback.IssueStatus.DELETED
                    feedback.save()
                    succeed_message.append("成功撤销反馈！")
        """
        # 如果有任何数据库操作，都需要提示操作成功
        if succeed_message:
            return redirect(message_url(succeed("，".join(succeed_message)), request.path))

    # 使用 GET 方法访问，展示页面
    # 首先确定不同用户对反馈的评论和修改权限
    read = feedback.get_read_status_display()
    solve = feedback.get_solve_status_display()
    public = False
    is_person = feedback.person == me
    commentable = False
    public_editable = False
    read_editable = False
    solve_editable = False
    cancel_editable = False  # 不允许修改反馈标题和反馈内容
    form_editable = False
    # 一、当前登录用户为发布者
    if user_type == UTYPE_PER and feedback.person == me:
        login_identity = "publisher"
        # 未结束反馈发布者可评论，可撤销
        if feedback.solve_status in (Feedback.SolveStatus.SOLVING, Feedback.SolveStatus.UNMARKED) \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            commentable = True
            # 撤销反馈功能迁移到反馈聚合页面
            # cancel_editable = True
        # 未公开反馈，且老师没有设置成不予公开时，发布者可修改自身公开状态
        if (not feedback.publisher_public) and feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            public_editable = True
    # 二、当前登录用户为老师
    elif user_type == UTYPE_PER and me.is_teacher():
        login_identity = "teacher"
        # 未结束反馈可评论
        if feedback.solve_status in (Feedback.SolveStatus.SOLVING, Feedback.SolveStatus.UNMARKED) \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            commentable = True
        # 所有反馈老师可修改公开状态
        if feedback.issue_status != Feedback.IssueStatus.DELETED:
            public_editable = True
        if feedback.public_status == Feedback.PublicStatus.PUBLIC \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            public = True
        # 未结束反馈可评论
        if feedback.solve_status in (Feedback.SolveStatus.SOLVING, Feedback.SolveStatus.UNMARKED) \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            commentable = True
    # 三、当前登录用户为发布者和老师以外的个人
    elif user_type == UTYPE_PER:
        # 检查当前个人是否具有访问权限，只有公开反馈有访问权限
        if feedback.public_status == Feedback.PublicStatus.PUBLIC \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            login_identity = "student"
        else:
            # 如果是组织管理员，尝试登录
            login_context = utils.user_login_org(request, feedback.org)
            if login_context["warn_code"] == SUCCEED:
                return redirect(message_url(login_context, request.path))
            return redirect(message_url(wrong("该反馈尚未公开，没有访问该反馈的权限！"), '/feedback/'))
    # 四、当前登录用户为受反馈小组
    elif user_type == UTYPE_ORG and feedback.org == me:
        login_identity = "org"
        # 未读反馈可修改未为已读
        if feedback.read_status == Feedback.ReadStatus.UNREAD \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            read_editable = True
        # 未结束反馈可修改为已结束，并且可以评论
        if feedback.solve_status in (Feedback.SolveStatus.SOLVING, Feedback.SolveStatus.UNMARKED) \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            solve_editable = True
            commentable = True
        # 个人愿意公开，老师没有设置成不予公开时，组织可修改自身公开状态
        if feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE \
            and feedback.issue_status != Feedback.IssueStatus.DELETED:
            public_editable = True
    # 其他用户（非受反馈小组）暂时不开放任何权限
    else:
        return redirect(message_url(wrong("没有访问该反馈的权限"), '/feedback/'))

    # 撤销反馈、公开反馈、标记已读、修改解决状态需要表单操作
    # 撤销反馈迁移到反馈聚合页面
    form_editable = public_editable or read_editable or solve_editable

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="反馈信息")
    title = feedback.title
    comments = showComment(feedback, anonymous_users=[feedback.person.person_id])
    return render(request, "feedback_info.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='feedback_views[feedbackWelcome]', record_user=True)
def feedbackWelcome(request: HttpRequest):
    valid, user_type, html_display = utils.check_user_type(request.user)
    is_person = user_type == UTYPE_PER
    me = get_person_or_org(request.user, user_type)

    # 准备用户提示量
    my_messages.transfer_message_context(request.GET, html_display)

    # -----------------------------反馈记录---------------------------------
    issued_feedback = (
        Feedback.objects
        .filter(issue_status=Feedback.IssueStatus.ISSUED)
        .order_by("-feedback_time")
    )

    # 是否显示我的反馈
    show_feedback = True
    if user_type == UTYPE_PER:
        # 教师页面不显示我的反馈
        if me.is_teacher():
            show_feedback = False
        my_feedback = issued_feedback.filter(person_id=me)
        my_all_feedback = Feedback.objects.filter(person_id=me)
    else:
        my_feedback = issued_feedback.filter(org_id=me)
        my_all_feedback = Feedback.objects.filter(org_id=me)

    undone_feedback = (
        my_feedback
        .filter(
            Q(solve_status=Feedback.SolveStatus.SOLVING)
            | Q(solve_status=Feedback.SolveStatus.UNMARKED)
        )
    )
    done_feedback = (
        my_all_feedback
        .filter(
            Q(solve_status=Feedback.SolveStatus.SOLVED)
            | Q(solve_status=Feedback.SolveStatus.UNSOLVABLE)
            | Q(issue_status=Feedback.IssueStatus.DELETED)
        )
    )

    # -----------------------------留言公开---------------------------------
    public_feedback = (
        Feedback.objects
        .filter(public_status=Feedback.PublicStatus.PUBLIC)
        .filter(issue_status=Feedback.IssueStatus.ISSUED)
        .order_by("-feedback_time")
    )

    # 我已处理
    # 已公开的或者强制不公开（不予公开）的是已经处理过的
    process_feedback = (
        Feedback.objects
        .filter(Q(public_status=Feedback.PublicStatus.PUBLIC) | Q(public_status=Feedback.PublicStatus.FORCE_PRIVATE))
        .filter(issue_status=Feedback.IssueStatus.ISSUED)
        .order_by("-feedback_time")
    )

    # -----------------------------反馈草稿---------------------------------
    # 准备需要呈现的内容
    # 这里应该呈现：所有person为自己的feedback
    draft_feedback = my_all_feedback.filter(issue_status=Feedback.IssueStatus.DRAFTED)
    # -----------------------------老师审核---------------------------------

    is_teacher = me.is_teacher() if is_person else False
    my_wait_public = []
    my_public_feedback = []
    my_process_feedback = []  # 我已处理列表
    wait_public = (
        issued_feedback
        .filter(publisher_public=True, org_public=True)
        .filter(public_status=Feedback.PublicStatus.PRIVATE)
    )
    if is_teacher:
        for feedback in wait_public:
            can_show = me.incharge.filter(otype_id=feedback.org.otype_id)
            if can_show.exists():
                my_wait_public.append(feedback)

        for feedback in public_feedback:
            can_show = me.incharge.filter(otype_id=feedback.org.otype_id)
            if can_show.exists():
                my_public_feedback.append(feedback)

        # 获取我已处理列表
        for feedback in process_feedback:
            can_show = me.incharge.filter(otype_id=feedback.org.otype_id)
            if can_show.exists():
                my_process_feedback.append(feedback)

    if request.method == "POST":
        option = request.POST.get("option")
        if not is_person:
            return redirect(message_url(wrong('组织不可以撤回/删除反馈!'), request.path))
        if option not in ["delete", "withdraw"]:
            return redirect(message_url(wrong('无效的请求!'), request.path))

        if option == "delete":
            try:
                del_feedback = Feedback.objects.get(id=request.POST["id"])
            except Exception:
                return redirect(message_url(wrong("不存在这样的反馈！"), request.path))
            # 合法性检查
            if del_feedback.issue_status == Feedback.IssueStatus.ISSUED:
                return redirect(message_url(wrong('不能删除已经发布的反馈！'), request.path))
            if del_feedback.issue_status == Feedback.IssueStatus.DELETED:
                return redirect(message_url(wrong('这条反馈已经被删除啦！'), request.path))

            with transaction.atomic():
                del_feedback.issue_status = Feedback.IssueStatus.DELETED
                del_feedback.save()
            succeed('成功删除反馈草稿！', html_display)

        elif option == "withdraw":
            try:
                del_feedback = Feedback.objects.get(id=request.POST["id"])
            except Exception:
                return redirect(message_url(wrong("不存在这样的反馈！"), request.path))
            # 合法性检查
            if del_feedback.issue_status != Feedback.IssueStatus.ISSUED:
                return redirect(message_url(wrong('不能撤回没有发布的反馈！'), request.path))
            if del_feedback.issue_status == Feedback.IssueStatus.DELETED:
                return redirect(message_url(wrong('这条反馈已经被撤回啦！'), request.path))
            if del_feedback.solve_status in [
                Feedback.SolveStatus.SOLVED,
                Feedback.SolveStatus.UNSOLVABLE,
            ]:
                return redirect(message_url(wrong('不能撤回已经发布的反馈！'), request.path))

            with transaction.atomic():
                del_feedback.issue_status = Feedback.IssueStatus.DELETED
                del_feedback.save()
            succeed('成功撤回反馈！', html_display)

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="反馈中心")

    return render(request, "feedback_welcome.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='feedback_views[modifyFeedback]', record_user=True)
def modifyFeedback(request: HttpRequest):
    '''
    反馈表单填写、修改与提交的视图函数
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)

    # 设置feedback为None, 如果非None则自动覆盖
    feedback = None

    # 根据是否有newid来判断是否是第一次
    feedback_id = request.GET.get("feedback_id")

    # 获取前端页面中可能存在的提示
    my_messages.transfer_message_context(request.GET, html_display)

    if feedback_id is not None: # 如果存在对应反馈
        try:   # 尝试读取已有的Feedback存档
            feedback = Feedback.objects.get(id=feedback_id)
            # 接下来检查是否有权限check这个条目，应该是本人/对应组织
            assert (feedback.person == me) or (feedback.org == me)
        except: #恶意跳转
            return redirect(message_url(wrong("您没有权限访问该网址！")))
        is_new_feedback = False # 前端使用量, 表示是已有的反馈还是新的

    else:
        # 如果不存在id, 是一个新建反馈页面。
        feedback = None
        is_new_feedback = True

    '''
        至此，如果是新反馈那么feedback为None，否则为对应反馈
        feedback = None只有在个人新建反馈的时候才可能出现，对应为is_new_feedback
        接下来POST
    '''

    if request.method == "POST":
        context = update_feedback(feedback, me, request)

        if context["warn_code"] == 2:   # 成功修改
            feedback = Feedback.objects.get(id=context["feedback_id"])
            is_new_application = False  # 状态变更
            # 处理通知相关的操作
            try:
                feasible_post = [
                    "directly_submit",
                    "submit_draft",
                ]
                if request.POST.get('post_type') in feasible_post:
                    make_relevant_notification(feedback, request.POST, me)
            except:
                return redirect(message_url(
                                wrong("返回了未知类型的post_type，请注意检查！"),
                                request.path))

        elif context["warn_code"] != 1: # 没有返回操作提示
            return redirect(message_url(
                            wrong("在处理反馈中出现了未预见状态，请联系管理员处理！"),
                            request.path))

        # 准备用户提示量
        my_messages.transfer_message_context(context, html_display)

        # 为了保证稳定性，完成POST操作后同意全体回调函数，进入GET状态
        if feedback is None:
            return redirect(message_url(context, '/modifyFeedback/'))
        elif feedback.issue_status == Feedback.IssueStatus.DRAFTED:
            return redirect(message_url(context, f'/modifyFeedback/?feedback_id={feedback.id}'))
        else: # 发布，feedback.issue_status == Feedback.IssueStatus.ISSUED
            return redirect(message_url(context, f'/viewFeedback/{feedback.id}'))

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    feedback_type_list = {
        fbtype.name:{
            'value'   : fbtype.name,
            'display' : fbtype.name,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for fbtype in FeedbackType.objects.all()
    }

    org_type_list = {
        otype.otype_name:{
            'value'   : otype.otype_name,
            'display' : otype.otype_name,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for otype in OrganizationType.objects.all()
    }

    org_list = {
        org.oname:{
            'value'   : org.oname,
            'display' : org.oname,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for org in Organization.objects.all()
    }

    org_type_list[''] = {
        'value': '', 'display': '', 'disabled': False, 'selected': False,
    }
    org_list[''] = {
        'value': '', 'display': '', 'disabled': False, 'selected': False,
    }

    # 用户写表格?
    if (is_new_feedback or (feedback.person == me and feedback.issue_status == Feedback.IssueStatus.DRAFTED)):
        allow_form_edit = True
    else:
        allow_form_edit = False

    # 用于前端展示
    feedback_person = me if is_new_feedback else feedback.person
    app_avatar_path = feedback_person.get_user_ava()
    all_org_types = [otype.otype_name for otype in OrganizationType.objects.all()]
    all_org_list = []
    for otype in all_org_types:
        all_org_list.append(([otype,] +
            [org.oname for org in Organization.objects.filter(
                otype=OrganizationType.objects.get(otype_name=otype)
            )]) if otype != '' else ([otype,] + [
                org.oname for org in Organization.objects.all()
            ])
        )
    fbtype_to_org = [] #存有多个列表，每个列表为[fbtype, orgtype, org]，用于前端变换下拉选项
    for fbtype in feedback_type_list.keys():
        fbtype_obj = FeedbackType.objects.get(name=fbtype)
        fbtype_to_org.append([fbtype,] + ([
            fbtype_obj.org_type.otype_name,
        ] if fbtype_obj.org_type else ['',]) + ([
            fbtype_obj.org.oname,
        ] if fbtype_obj.org else ['',])
        )
    if not is_new_feedback:
        feedback_type_list[feedback.type.name]['selected'] = True
        if feedback.org_type is not None:
            org_type_list[feedback.org_type.otype_name]['selected'] = True
            for org in Organization.objects.exclude(
                    otype=OrganizationType.objects.get(
                        otype_name=feedback.org_type.otype_name)
                    ):
                org_list[org.oname]['disabled'] = True
        else:
            org_type_list['']['selected'] = True
            for org in org_list.keys():
                org_list[org]['disabled'] = True
        if feedback.org is not None:
            org_list[feedback.org.oname]['selected'] = True
        else:
            org_list['']['selected'] = True
    else: # feedback_type 默认选中第一个反馈类型，默认选中项将在前端实时更新。
        feedback_type = list(feedback_type_list.keys())[0]
        if FeedbackType.objects.get(name=feedback_type).org_type is not None:
            org_type_list[
                FeedbackType.objects.get(name=feedback_type).org_type.otype_name
            ]['selected'] = True
            for org in Organization.objects.exclude(
                    otype=OrganizationType.objects.get(
                        otype_name=FeedbackType.objects.get(name=feedback_type).org_type.otype_name)
                    ):
                org_list[org.oname]['disabled'] = True
        else:
            org_type_list['']['selected'] = True
            for org in org_list.keys():
                org_list[org]['disabled'] = True
        if FeedbackType.objects.get(name=feedback_type).org is not None:
            org_list[
                FeedbackType.objects.get(name=feedback_type).org.oname
            ]['selected'] = True
        else:
            org_list['']['selected'] = True
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="填写反馈" if is_new_feedback else "反馈详情"
    )
    return render(request, "modify_feedback.html", locals())
