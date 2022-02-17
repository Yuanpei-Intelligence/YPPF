from app.utils_dependency import *
from app.models import (
    Organization,
    Notification,
    FeedbackType,
    Feedback,
)
from app.notification_utils import (
    notification_create,
)

__all__ = [
    'check_feedback',
    'update_feedback',
    'make_relevant_notification',
]


def check_feedback(request, post_type):
    '''返回feedback的context字典，如果是提交反馈则检查feedback参数的合法性'''
    context = dict()
    context["warn_code"] = 0
    
    try:
        type = str(request.POST.get("type"))
        context["type"] = FeedbackType.objects.get(name=type)
    except:
        context["warn_code"] = 1
        # User can't see it. We use it for debugging.
        context["warn_message"] = "数据库没有对应反馈类型，请联系管理员！"
        return context
    
    try:
        org = str(request.POST.get("org"))
        context["org"] = Organization.objects.get(oname=org)
    except:
        context["warn_code"] = 1
        # User can't see it. We use it for debugging.
        context["warn_message"] = "数据库没有对应小组，请联系管理员！"
        return context
    
    title = str(request.POST["title"])
    content = str(request.POST["content"])
    publisher_public = str(request.POST['publisher_public'])
    
    # 草稿不用检查标题、内容、公开的合法性，提交反馈需要检查！
    if post_type in {"directly_submit", "submit_draft"}:
        if len(title) >= 30:
            return wrong("标题不能超过30字哦！")
        if title == "":
            return wrong("标题不能为空哦！")
        
        if content == "":
            return wrong("反馈内容不能为空哦！")
        
        if publisher_public == "":
            return wrong("必须选择同意/不同意公开~")

    context["title"] = title                               # 反馈标题
    context["person"] = request.user                       # 反馈发出者
    context["content"] = str(request.POST.get("content"))  # 反馈内容
    context["publisher_public"] = True if request.POST.get("publisher_public")=="公开" else False
                                                           # 个人是否同意公开
    return context


def update_feedback(feedback, me, request):
    '''
    修改反馈详情的操作函数, feedback为修改的对象，可以为None
    me为操作者
    info为前端POST字典
    返回值为context, warn_code = 1表示失败, 2表示成功; 错误信息在context["warn_message"]
    如果成功context会返回update之后的feedback,
    '''

    # 首先上锁
    with transaction.atomic():
        info = request.POST
        post_type = info.get("post_type")
        
        context = check_feedback(request, post_type)
        if context['warn_code'] == 1:
            return context
        
        # TODO：删除草稿的功能
        if post_type == 'save':
            feedback = Feedback.objects.create(
                type=FeedbackType.objects.select_for_update().get(
                    name=info.get('type')
                ),
                title=info.get('title'),
                content=info.get('content'),
                person=me,
                org=Organization.objects.select_for_update().get(
                    oname=info.get('org')
                ),
                publisher_public=True if info.get('publisher_public')=='公开' else False,
                issue_status=Feedback.IssueStatus.DRAFTED,
            )
            context = succeed("成功将反馈保存成草稿！")
            context['feedback_id'] = feedback.id
            return context
        elif post_type == 'directly_submit':
            feedback = Feedback.objects.create(
                type=FeedbackType.objects.select_for_update().get(
                    name=info.get('type')
                ),
                title=info.get('title'),
                content=info.get('content'),
                person=me,
                org=Organization.objects.select_for_update().get(
                    oname=info.get('org')
                ),
                publisher_public=True if info.get('publisher_public')=='公开' else False,
                issue_status=Feedback.IssueStatus.ISSUED,
            )
            context = succeed(
                "成功提交反馈“" + info.get('title') + "”！" +
                "请耐心等待" + info.get('org') + "处理！"
            )
            context['feedback_id'] = feedback.id
            return context
        elif post_type == 'modify':
            if feedback.type != FeedbackType.objects.get(name=info.get('type')):
                return wrong("修改申请时不允许修改反馈类型。如确需修改，请取消后重新提交!")
            publisher_public = True if info.get('publisher_public')=='公开' else False
            if (feedback.title == info.get("title")
                    and feedback.content == info.get('content')
                    and feedback.publisher_public == publisher_public
                    and feedback.org == Organization.objects.get(oname=info.get('org'))):
                return wrong("没有检测到修改！")
            Feedback.objects.filter(id=feedback.id).update(
                title=info.get('title'),
                content=info.get('content'),
                publisher_public=publisher_public,
                org=Organization.objects.select_for_update().get(
                    oname=info.get('org')
                ),
            )
            context = succeed("成功修改反馈“" + info.get('title') + "”！点击“提交反馈”可提交~")
            context["feedback_id"] = feedback.id
            return context
        elif post_type == 'submit_draft':
            publisher_public = True if info.get('publisher_public')=='公开' else False
            Feedback.objects.filter(id=feedback.id).update(
                title=info.get('title'),
                content=info.get('content'),
                publisher_public=publisher_public,
                org=Organization.objects.select_for_update().get(
                    oname=info.get('org')
                ),
                issue_status=Feedback.IssueStatus.ISSUED,
            )
            context = succeed(
                "成功提交反馈“" + info.get('title') + "”！" +
                "请耐心等待" + info.get('org') + "处理！"
            )
            context['feedback_id'] = feedback.id
            return context


@log.except_captured(source='feedback_utils[make_relevant_notification]')
def make_relevant_notification(feedback, info, me):
    '''
    在用户提交反馈后，向对应组织发送通知
    '''
    
    post_type = info.get("post_type")
    feasible_post = [
        "directly_submit",
        "submit_draft",
    ]

    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    sender = me.person_id
    receiver = Organization.objects.get(oname=info.get('org')).organization_id
    typename = (Notification.Type.NEEDDO
                if post_type == 'new_submit'
                else Notification.Type.NEEDREAD)
    title = Notification.Title.FEEDBACK_INFORM
    content = "您收到一条新的反馈～点击标题立刻查看！"
    # TODO：小组看到的反馈详情呈现
    # URL = f'/modifyFeedback/?feedback_id={feedback.id}'
    relate_instance = feedback

    # 正式创建notification
    notification_create(
        receiver=receiver,
        sender=sender,
        typename=typename,
        title=title,
        content=content,
        URL=None,
        relate_instance=relate_instance,
        anonymous_flag=True,
    )
