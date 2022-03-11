from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Notification,
    FeedbackType,
    Feedback,
)
from app.notification_utils import (
    notification_create,
)
from app.wechat_send import (
    WechatApp,
    WechatMessageLevel,
)


__all__ = [
    'check_feedback',
    'update_feedback',
    'make_relevant_notification',
]


def check_feedback(request, post_type, me):
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
        otype = request.POST.get("otype")
        if otype:
            context["otype"] = OrganizationType.objects.get(otype_name=otype)
    except:
        context["warn_code"] = 1
        # User can't see it. We use it for debugging.
        context["warn_message"] = "数据库没有对应小组类型，请联系管理员！"
        return context
    
    try:
        org = request.POST.get("org")
        if org:
            context["org"] = Organization.objects.get(oname=org)
    except:
        context["warn_code"] = 1
        # User can't see it. We use it for debugging.
        context["warn_message"] = "数据库没有对应小组，请联系管理员！"
        return context
    
    title = str(request.POST["title"])
    otype = str(request.POST.get("otype"))      # 接收小组类型
    org = str(request.POST.get("org"))
    content = str(request.POST["content"])
    publisher_public = str(request.POST['publisher_public'])
    
    # 草稿不用检查标题、内容、公开的合法性，提交反馈需要检查！
    if post_type in ["directly_submit", "submit_draft"]:
        if len(title) >= 30:
            return wrong("标题不能超过30字哦！")
        if title == "":
            return wrong("标题不能为空哦！")
        
        if otype == "":
            return wrong("不能不选择接收小组的类型哦！")
        
        if org == "":
            return wrong("不选择接收小组就没有小组收到你的反馈了哦！请选择接收小组~")
        
        if content == "":
            return wrong("反馈内容不能为空哦！")
        
        if publisher_public == "":
            return wrong("必须选择同意/不同意公开~")

        if OrganizationType.objects.get(otype_name=otype).incharge == me:
            return wrong("老师您好，本系统暂不支持给您管理的小组发送反馈！抱歉。")

    context["title"] = title                               # 反馈标题
    context["person"] = request.user                       # 反馈发出者
    context["otype"] = str(request.POST.get("otype"))      # 接收小组类型
    context["org"] = str(request.POST.get("org"))          # 接收小组
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
        post_type = str(info.get("post_type"))
        
        context = check_feedback(request, post_type, me)
        if context['warn_code'] == 1:
            return context
        
        # TODO：删除草稿的功能
        content = dict(
            type=FeedbackType.objects.get(name=str(info.get('type'))),
            title=str(info.get('title')),
            content=str(info.get('content')),
            person=me,
            org_type=OrganizationType.objects.get(
                otype_name=str(info.get('otype'))
            ) if info.get('otype') else None,
            org=Organization.objects.get(
                oname=str(info.get('org'))
            ) if info.get('org') else None,
            publisher_public=(str(info.get('publisher_public')) == '公开'),
        )
        if post_type == 'save':
            feedback = Feedback.objects.create(
                **content,
                issue_status=Feedback.IssueStatus.DRAFTED,
            )
            context = succeed("成功将反馈保存成草稿！")
            context['feedback_id'] = feedback.id
            return context
        elif post_type == 'directly_submit':
            feedback = Feedback.objects.create(
                **content,
                issue_status=Feedback.IssueStatus.ISSUED,
            )
            context = succeed(
                "成功提交反馈“" + str(info.get('title')) + "”！" +
                "请耐心等待" + str(info.get('org')) + "处理！"
            )
            context['feedback_id'] = feedback.id
            return context
        elif post_type == 'modify':
            publisher_public = True if str(info.get('publisher_public'))=='公开' else False
            if (feedback.title == str(info.get("title"))
                    and feedback.type == FeedbackType.objects.get(name=str(info.get('type')))
                    and feedback.content == str(info.get('content'))
                    and feedback.publisher_public == publisher_public
                    and feedback.org == (Organization.objects.get(oname=str(info.get('org'))) 
                            if str(info.get('org')) else None)
                    ):
                return wrong("没有检测到修改！")
            Feedback.objects.filter(id=feedback.id).update(
                **content,
            )
            context = succeed("成功修改反馈“" + str(info.get('title')) + "”！点击“提交反馈”可提交~")
            context["feedback_id"] = feedback.id
            return context
        elif post_type == 'submit_draft':
            Feedback.objects.filter(id=feedback.id).update(
                **content,
                issue_status=Feedback.IssueStatus.ISSUED,
            )
            context = succeed(
                "成功提交反馈“" + str(info.get('title')) + "”！" +
                "请耐心等待" + str(info.get('org')) + "处理！"
            )
            context['feedback_id'] = feedback.id
            return context


@log.except_captured(source='feedback_utils[make_relevant_notification]')
def make_relevant_notification(feedback, info, me):
    '''
    在用户提交反馈后，向对应组织发送通知
    '''
    
    post_type = str(info.get("post_type"))
    feasible_post = [
        "directly_submit",
        "submit_draft",
    ]

    # 准备创建notification需要的构件：发送方、接收方、发送内容、通知类型、通知标题、URL、关联外键
    sender = me.person_id
    receiver = Organization.objects.get(oname=str(info.get('org'))).organization_id
    typename = (Notification.Type.NEEDDO
                if post_type == 'new_submit'
                else Notification.Type.NEEDREAD)
    title = f"反馈：{feedback.title}"
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
        URL=f"/viewFeedback/{feedback.id}",
        relate_instance=relate_instance,
        anonymous_flag=True,
        publish_to_wechat=True,
        publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.IMPORTANT},
    )


@log.except_captured(source='feedback_utils[examine_notification]')
def examine_notification(feedback):
    examin_teacher = feedback.org.otype.incharge.person_id
    notification_create(
        receiver=examin_teacher,
        sender=feedback.org.organization_id,
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.VERIFY_INFORM,
        content=f"{feedback.org.oname}申请公开一条反馈信息",
        URL=f"/viewFeedback/{feedback.id}",
        publish_to_wechat=True,
        publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
    )

@log.except_captured(source='feedback_utils[inform_notification]')
def inform_notification(sender: ClassifiedUser, receiver: ClassifiedUser,
                        content, feedback, anonymous=None, important=False):
    '''
    根据信息创建通知并发送到微信

    Parameters
    ----------
    content : str
        消息内容
    feedback : Feedback
        只使用id用于创建URL
    anonymous : bool, optional
        是否匿名，默认个人匿名
    important : bool, optional
        微信发送的等级, by default False
    '''
    if anonymous is None:
        anonymous = not isinstance(sender, Organization)
    level = WechatMessageLevel.IMPORTANT if important else WechatMessageLevel.INFO
    notification_create(
        receiver=receiver.get_user(),
        sender=sender.get_user(),
        typename=Notification.Type.NEEDREAD,
        title=Notification.Title.FEEDBACK_INFORM,
        content=content,
        URL=f"/viewFeedback/{feedback.id}",
        anonymous_flag=anonymous,
        publish_to_wechat=True,
        publish_kws={'app': WechatApp.AUDIT, 'level': level},
    )