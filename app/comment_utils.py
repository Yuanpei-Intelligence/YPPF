from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Notification,
    Comment,
    CommentPhoto,
)
from django.contrib.auth.models import User
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
from typing import List


@log.except_captured(source='comment_utils[addComment]', record_user=True)
def addComment(request, comment_base, receiver=None, *,
               anonymous=False, notification_title=None) -> MESSAGECONTEXT:
    """添加评论

    Args:
    ----
    - request<WSGIRequest>: 传入的 request，其中 POST 参数至少应当包括：
        - comment_submit
        - comment
    - comment_base<Commentbase object>: 以 Commentbase 为基类的对象。
        - 目前的 Commentbase 对象只有五种：
            modifyposition，neworganization，reimbursement，activity，feedback。
            - 2022.8.17加入Chat，用于学术地图问答
        - 添加 Commentbase 类型需要在 `content` 和 `URL` 中添加键值对。
        - 注意：该对象会被调用**`save`保存**
    - receiver<User object/iterable>:
        - 为User object时，只向一个user发布通知消息；
        - 为iterable时，向该可迭代对象中的所有user发布通知消息。
        - 注意：**不批量创建**通知，receiver个数应为常量级

    Returns:
        context<dict>: 继承自wrong/succeed, 成功时包含new_comment
    """
    valid, user_type, html_display = check_user_type(request.user)
    sender = get_person_or_org(request.user)
    sender_name = "匿名者" if anonymous else sender.get_display_name()

    typename = comment_base.typename
    content = {
        'modifyposition': f'{sender_name}在成员变动申请留有新的评论',
        'neworganization': f'{sender_name}在新建小组中留有新的评论',
        'reimbursement': f'{sender_name}在经费申请中留有新的评论',
        'activity': f"{sender_name}在活动申请中留有新的评论",
        'feedback': f"{sender_name}在反馈中心留有新的评论",
        'Chat': f"{sender_name}给您发来了新提问" 
                    if request.user == comment_base.questioner 
                    else f"{sender_name}给您发来了新回答",
    }
    URL = {
        'modifyposition': f'/modifyPosition/?pos_id={comment_base.id}',
        'neworganization': f'/modifyOrganization/?org_id={comment_base.id}',
        'reimbursement': f'/modifyEndActivity/?reimb_id={comment_base.id}',
        'activity': f"/examineActivity/{comment_base.id}"
                    # 发送者如果是组织，接收者就是老师
                    if user_type == UTYPE_ORG else
                    f"/editActivity/{comment_base.id}",
        'feedback': f"/viewFeedback/{comment_base.id}",
        'Chat': f"/viewQA/{comment_base.id}"
    }
    # 原来提示语中都用“评论”指代comment，如“评论内容均为空，无法评论”“评论成功”等
    # 对于学术地图问答，用“问答”似乎更合理，故引入下面的映射
    # added by xpr 2022.8.17
    comment_name = {
        'modifyposition': '评论',
        'neworganization': '评论',
        'reimbursement': '评论',
        'activity': '评论',
        'feedback': '评论',
        'Chat': '问答',
    }

    # 新建评论信息，并保存
    if request.POST.get("comment_submit") is not None:
        text = str(request.POST.get("comment"))
        # 检查图片合法性
        comment_images = request.FILES.getlist('comment_images')
        if not text and not comment_images:
            return wrong(f"{comment_name[typename]}内容均为空，无法发送{comment_name[typename]}！")
        for comment_image in comment_images:
            if if_image(comment_image) != 2:
                return wrong(f"{comment_name[typename]}中上传的附件只支持图片格式。")
        try:
            with transaction.atomic():
                new_comment = Comment.objects.create(
                    commentbase=comment_base, commentator=request.user, text=text
                )
                for comment_image in comment_images:
                    CommentPhoto.objects.create(
                        image=comment_image, comment=new_comment
                    )
                comment_base.save()  # 每次save都会更新修改时间
        except:
            return wrong(f"发送{comment_name[typename]}失败，请联系管理员。")

        if len(text) >= 32:
            text = text[:31] + "……"
        if len(text) > 0:
            text = f'{content[typename]}：{text}'
        else:
            text = f'{content[typename]}。'

        if notification_title is None:
            notification_title = Notification.Title.VERIFY_INFORM
        # 向一个用户或多个用户发布消息
        if receiver is not None:
            receivers = receiver
            if isinstance(receivers, User):
                receivers = [receivers]
            # 向多个用户发布消息
            for _receiver in receivers:
                notification_create(
                    _receiver,
                    request.user,
                    Notification.Type.NEEDREAD,
                    notification_title,
                    text,
                    URL[typename],
                    publish_to_wechat=True,
                    publish_kws={'app': WechatApp.AUDIT, 'level': WechatMessageLevel.INFO},
                    anonymous_flag=anonymous,
                )
        context = succeed(f"发送{comment_name[typename]}成功。")
        context["new_comment"] = new_comment
        return context
    else:
        return wrong(f"找不到{comment_name[typename]}信息, 请重试!")


@log.except_captured(source='comment_utils[showComment]')
def showComment(commentbase, anonymous_users=None) -> List[dict]:
    '''
    获取可展示的对象相关评论，返回以时间顺序展示的评论列表，应赋值为`comments`
    '''
    if commentbase is None:
        return None
    try:
        comments: QuerySet[Comment] = commentbase.comments.order_by("time")
    except:
        return None
    comments_display = []
    anonymous_users = set() if anonymous_users is None else set(anonymous_users)
    for comment in comments:
        display = dict(
            text=comment.text,
            time=comment.time,
        )
        if anonymous_users and comment.commentator in anonymous_users:
            commentator_display = dict(
                name='匿名用户',
                avatar=NaturalPerson.get_user_ava(),
            )
        else:
            commentator = get_person_or_org(comment.commentator)
            commentator_display = dict(
                name=commentator.get_display_name(),
                avatar=commentator.get_user_ava(),
                URL=commentator.get_absolute_url(),
            )
        display.update(commentator=commentator_display)
        photos = list(comment.comment_photos.all())
        display.update(photos=photos)
        comments_display.append(display)
    return comments_display
