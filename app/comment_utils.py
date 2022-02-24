from app.utils_dependency import *
from app.models import (
    Notification,
    Comment,
    CommentPhoto,
)
from app.utils import (
    get_person_or_org,
    check_user_type,
    if_image,
)
from app.notification_utils import notification_create
from app.wechat_send import (
    WechatApp,
    WechatMessageLevel,
)


@log.except_captured(source='comment_utils[addComment]', record_user=True)
def addComment(request, comment_base, receiver=None, anonymous_flag=None, notification_title=None):
    """添加评论
    Args:
        request<WSGIRequest>: 传入的 request，其中 POST 参数至少应当包括：
            comment_submit，comment
        comment_base<Commentbase object>: 以 Commentbase 为基类的对象。
            - 目前的 Commentbase 对象只有五种：modifyposition，neworganization，reimbursement，activity，feedback。
            - 添加 Commentbase 类型需要在 `content` 和 `URL` 中添加键值对。
        receiver<User object/list/tuple>:
            - 为User object时，只向一个user发布通知消息；
            - 为list/tuple时，向该可迭代对象中的所有user发布通知消息。
    Returns:
        context<dict>: warn_code==1 代表添加失败，warn_code==2代表添加成功
    """
    valid, user_type, html_display = check_user_type(request.user)
    sender = get_person_or_org(request.user)
    if user_type == "Organization":
        sender_name = sender.oname
        anonymous_flag = False
    else:
        sender_name = sender.name if anonymous_flag is None else "匿名者"
    context = dict()
    typename = comment_base.typename
    content = {
        'modifyposition': f'{sender_name}在成员变动申请留有新的评论',
        'neworganization': f'{sender_name}在新建小组中留有新的评论',
        'reimbursement': f'{sender_name}在经费申请中留有新的评论',
        'activity': f"{sender_name}在活动申请中留有新的评论",
        'feedback': f"{sender_name}在反馈中心留有新的评论"
    }
    URL={
        'modifyposition': f'/modifyPosition/?pos_id={comment_base.id}',
        'neworganization': f'/modifyOrganization/?org_id={comment_base.id}',
        'reimbursement': f'/modifyEndActivity/?reimb_id={comment_base.id}',
        'activity': f"/examineActivity/{comment_base.id}",
        'feedback': f"/viewFeedback/{comment_base.id}"
    }
    if user_type == "Organization":
        URL["activity"] = f"/editActivity/{comment_base.id}"
    if request.POST.get("comment_submit") is not None:  # 新建评论信息，并保存
        text = str(request.POST.get("comment"))
        # 检查图片合法性
        comment_images = request.FILES.getlist('comment_images')
        if text == "" and comment_images == []:
            context['warn_code'] = 1
            context['warn_message'] = "评论内容均为空，无法评论！"
            return context
        if len(comment_images) > 0:
            for comment_image in comment_images:
                if if_image(comment_image) != 2:
                    context["warn_code"] = 1
                    context["warn_message"] = "评论中上传的附件只支持图片格式。"
                    return context
        try:
            with transaction.atomic():
                new_comment = Comment.objects.create(
                    commentbase=comment_base, commentator=request.user, text=text
                )
                if len(comment_images) > 0:
                    for comment_image in comment_images:
                        CommentPhoto.objects.create(
                            image=comment_image, comment=new_comment
                        )
                comment_base.save()  # 每次save都会更新修改时间
        except:
            context["warn_code"] = 1
            context["warn_message"] = "评论失败，请联系管理员。"
            return context
            
        if len(text) >= 32:
            text = text[:31] + "……"
        if len(text) > 0:
            content[typename] += f'：{text}'
        else:
            content[typename] += "。"
        
       
        if user_type == "Organization":
            URL["activity"] = f"/examineActivity/{comment_base.id}"
        else:
            URL["activity"] = f"/editActivity/{comment_base.id}"

        # 向一个用户或多个用户发布消息
        if receiver is not None:
            # 向多个用户发布消息
            if isinstance(receiver, (list, tuple)):
                for rec in receiver:
                    notification_create(
                        rec,
                        request.user,
                        Notification.Type.NEEDREAD,
                        Notification.Title.VERIFY_INFORM if notification_title is None else notification_title,
                        content[typename],
                        URL[typename],
                        publish_to_wechat=True,
                        publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
                        anonymous_flag=anonymous_flag,
                    )
            # 向一个用户发布消息
            else:
                notification_create(
                    receiver,
                    request.user,
                    Notification.Type.NEEDREAD,
                    Notification.Title.VERIFY_INFORM if notification_title is None else notification_title,
                    content[typename],
                    URL[typename],
                    publish_to_wechat=True,
                    publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
                    anonymous_flag=anonymous_flag,
                )
        context["new_comment"] = new_comment
        context["warn_code"] = 2
        context["warn_message"] = "评论成功。"
    else:
        return wrong("找不到评论信息, 请重试!")
    return context


@log.except_captured(source='comment_utils[showComment]')
def showComment(commentbase):
    if commentbase is None:
        return None
    try:
        comments = commentbase.comments.order_by("time")
    except:
        return None
    for comment in comments:
        commentator = get_person_or_org(comment.commentator)
        if comment.commentator.username[:2] == "zz":
            comment.ava = commentator.get_user_ava()
            comment.URL = "/orginfo/?name={name}".format(name=commentator.oname)
            comment.commentator_name = commentator.oname
        else:
            comment.ava = commentator.get_user_ava()
            comment.URL = "/stuinfo/?name={name}".format(name=commentator.name)
            comment.commentator_name = commentator.name
        comment.len = len(comment.comment_photos.all())
    comments.len = len(comments.all())
    return comments
