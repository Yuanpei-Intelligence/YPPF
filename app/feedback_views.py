from app.views_dependency import *
from app.models import (
    Feedback,
    NaturalPerson,
    Organization,
    OrganizationType,
    Feedback,
    FeedbackType,
)
from app.utils import (
    get_person_or_org,
)
from app.comment_utils import addComment, showComment
from django.db import transaction


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
# @log.except_captured(EXCEPT_REDIRECT, source='views[viewActivity]', record_user=True)
def viewFeedback(request, fid):
    """
    1. 使用 GET 方法访问，展示该反馈的详情页。
    2. 使用 POST 方法访问，可以添加评论以及修改状态。
    """
    # 查找fid对应的反馈条目
    fid = int(fid)
    feedback = Feedback.objects.get(id=fid)

    valid, user_type, html_display = utils.check_user_type(request.user)
    me = utils.get_person_or_org(request.user, user_type)

    # 添加评论和修改活动状态
    if request.method == "POST" and request.POST:
        option = request.POST.get("option")
        # 添加评论
        if option == "comment":
            # 确定通知消息的发送人，互相发送给对方
            if user_type == "Person" and feedback.person == me:
                receiver = feedback.org
            elif user_type == "Organization" and feedback.org == me:
                receiver = feedback.person
            # TODO: 当评论者是其他人的时候（公开反馈），要向哪些人发送通知提醒？
            # 之前评论过的学生/老师可以收到提醒吗？
            # 暂时没有发送任何消息提醒，addComment函数不支持向多人发送提醒
            else:
                receiver = None
            addComment(request, feedback, receiver)
        # 以下为调整反馈的状态
        # 一、公开反馈信息
        elif option == "public":
            # 组织选择公开反馈
            if user_type == "Organization" and feedback.org == me:
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.org_public = True
                    # 若老师没有强制隐藏，发布者也选择公开反馈，则修改公开状态
                    if (
                        feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE
                        and feedback.publisher_public == True
                    ):
                        feedback.public_status = Feedback.PublicStatus.PUBLIC
                    feedback.save()
            # 发布者（个人）选择公开反馈
            elif user_type == "Person" and feedback.person == me:
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.publisher_public = True
                    # 若老师没有强制隐藏，若组织也选择公开反馈，则修改公开状态
                    if (
                        feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE
                        and feedback.org_public == True
                    ):
                        feedback.public_status = Feedback.PublicStatus.PUBLIC
                    feedback.save()
            # 其他人没有公开反馈权限
            else:
                redirect(message_url(wrong("没有公开该反馈的权限！")))
        # 二、隐藏反馈信息
        elif option == "private":
            # 组织选择隐藏反馈
            if user_type == "Organization" and feedback.org == me:
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.org_public = False
                    # 此时若老师没有强制隐藏，则隐藏反馈状态
                    if feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE:
                        feedback.public_status = Feedback.PublicStatus.PRIVATE
                    feedback.save()
            # 发布者（个人）选择隐藏反馈
            elif user_type == "Person" and feedback.person == me:
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.publisher_public = False
                    # 此时若老师没有强制隐藏，则隐藏反馈状态
                    if feedback.public_status != Feedback.PublicStatus.FORCE_PRIVATE:
                        feedback.public_status = Feedback.PublicStatus.PRIVATE
                    feedback.save()
            # 教师选择隐藏反馈
            elif (
                user_type == "Person" and me.identity == NaturalPerson.Identity.TEACHER
            ):
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    # 教师为强制隐藏
                    feedback.public_status = Feedback.PublicStatus.FORCE_PRIVATE
                    feedback.save()
            # 其他人没有隐藏反馈权限
            else:
                redirect(message_url(wrong("没有隐藏该反馈的权限！")))
        # 三、修改已读状态
        elif option == "read":
            # 只有组织可以修改已读状态
            if user_type == "Organization" and feedback.org == me:
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    feedback.read_status = Feedback.ReadStatus.READ
                    feedback.save()
            # 其他人没有标记已读权限
            else:
                redirect(message_url(wrong("没有修改已读状态的权限！")))
        # 四、修改解决状态
        elif option == "solve":
            print(request.POST)
            # 只有组织可以修改解决状态
            if user_type == "Organization" and feedback.org == me:
                with transaction.atomic():
                    feedback = Feedback.objects.select_for_update().get(id=fid)
                    # 修改为已解决
                    if request.POST["solve_status"] == "solve":
                        feedback.solve_status = Feedback.SolveStatus.SOLVED
                    # 修改为无法解决
                    elif request.POST["solve_status"] == "unsolvable":
                        feedback.solve_status = Feedback.SolveStatus.UNSOLVABLE
                    feedback.save()
            # 其他人没有修改解决状态权限
            else:
                redirect(message_url(wrong("没有修改解决状态的权限！")))

    # 使用 GET 方法访问，展示页面
    # 首先确定不同用户对反馈的评论和修改权限
    commentable = False
    make_public = False
    make_private = False
    read_editable = False
    solve_editable = False
    # 当前登录用户为发布者
    if user_type == "Person" and feedback.person == me:
        login_identity = "publisher"
        commentable = True
        # 发布者可修改自身公开状态
        if feedback.publisher_public:
            make_private = True
        else:
            make_public = True
    # 当前登录用户为老师
    elif user_type == "Person" and me.identity == NaturalPerson.Identity.TEACHER:
        login_identity = "teacher"
        commentable = True
        # 老师只有隐藏反馈权限
        if feedback.public_status == Feedback.PublicStatus.PUBLIC:
            make_private = True
    # 当前登录用户为发布者和老师以外的个人
    elif user_type == "Person":
        # 检查当前个人是否具有访问权限，只有公开反馈有访问权限
        if feedback.public_status == Feedback.PublicStatus.PUBLIC:
            login_identity = "student"
            commentable = True
        else:
            return redirect(message_url(wrong("该反馈尚未公开，没有访问该反馈的权限！")))
    # 当前登录用户为受反馈小组
    elif user_type == "Organization":
        # 检查当前小组是否具有访问权限，只有被反馈小组有权限
        if feedback.org == me:
            login_identity = "org"
            commentable = True
            read_editable = True
            solve_editable = True
            # 组织可修改自身公开状态
            if feedback.org_public:
                make_private = True
            else:
                make_public = True
        else:
            return redirect(message_url(wrong("非受反馈小组没有访问该反馈的权限")))
    # 其他用户（好像也没有除小组和个人以外的用户？先写上else保证不会遗漏）
    # 暂时不开放任何权限
    else:
        redirect(message_url(wrong("没有访问该反馈的权限")))

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="反馈信息")
    title = feedback.title
    comments = showComment(feedback)
    return render(request, "feedback_info.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='feedback_views[feedbackWelcome]', record_user=True)
def feedbackWelcome(request):
    '''
    【我要留言】的初始化页面，呈现反馈提醒、选择反馈类型
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)
    my_messages.transfer_message_context(request.GET, html_display)

    feedback_type_list = list(FeedbackType.objects.all())
    
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="我要留言"
    )
    return render(request, "feedback_welcome.html", locals())
