from app.utils_dependency import *
from app.models import (
    User,
    Chat,
)
from app.comment_utils import addComment
from app.utils import check_user_type

from django.http import HttpRequest
from typing import Tuple

__all__ = [
    'change_chat_status', 'add_chat_message', 'create_chat',
]


def change_chat_status(chat_id: int, to_status: Chat.Status) -> MESSAGECONTEXT:
    """
    修改chat的状态

    :param chat_id
    :type chat_id: int
    :param to_status: 目标状态
    :type to_status: Chat.Status
    :return: 表明成功与否的MESSAGECONTEXT
    :rtype: MESSAGECONTEXT
    """
    # 参考了notification_utils.py的notification_status_change
    context = wrong("在修改问答状态的过程中发生错误，请联系管理员！")
    with transaction.atomic():
        try:
            chat: Chat = Chat.objects.select_for_update().get(id=chat_id)
        except:
            return wrong("该问答不存在！", context)
        
        if chat.status == to_status:
            return succeed("问答状态无需改变！", context)
        
        if to_status == Chat.Status.CLOSED:
            chat.status = Chat.Status.CLOSED
            chat.save()
            succeed("您已成功关闭一个问答！", context)
        elif to_status == Chat.Status.PROGRESSING: # 这个目前没有用到
            raise NotImplementedError
            chat.status = Chat.Status.PROGRESSING
            chat.save()
            succeed("您已成功开放一个问答！", context)
        return context


def add_chat_message(request: HttpRequest, chat: Chat) -> MESSAGECONTEXT:
    """
    给一个chat发送新comment，并给接收者发通知（复用了comment_utils.py/addComment）

    :param request: addComment函数会用到，其user即为发送comment的用户，其POST参数至少应当包括：comment_submit（点击“回复”按钮），comment（回复内容）
    :type request: HttpRequest
    :param chat
    :type chat: Chat
    :return: 表明发送结果的MESSAGECONTEXT
    :rtype: MESSAGECONTEXT
    """
    # 只能发给PROGRESSING的chat
    if chat.status == Chat.Status.CLOSED:
        return wrong("当前问答已关闭，无法发送新信息!")
    if (not chat.respondent.accept_anonymous_chat) and chat.anonymous:
        if request.user == chat.respondent:
            return wrong("您目前处于禁用匿名提问状态!")
        else:
            return wrong("对方目前不允许匿名提问!")
    
    if request.user == chat.questioner:
        receiver = chat.respondent # 我是这个chat的提问方，则我发送新comment时chat的接收方会收到通知
        anonymous = chat.anonymous # 如果chat是匿名提问的，则我作为提问方发送新comment时需要匿名
    else:
        receiver = chat.questioner # 我是这个chat的接收方，则我发送新comment时chat的提问方会收到通知
        anonymous = False # 接收方发送的comment一定是实名的
    
    comment_context = addComment( # 复用comment_utils.py，这个函数包含了通知发送功能
        request, chat, receiver, anonymous=anonymous, notification_title='学术地图问答信息')
    return comment_context


def create_chat(request: HttpRequest, respondent: User, title: str, anonymous: bool=False) -> Tuple[int, MESSAGECONTEXT]:
    """
    创建新chat并调用add_chat_message发送首条提问

    :param request: add_chat_message会用到
    :type request: HttpRequest
    :param respondent: 被提问的人
    :type respondent: User
    :param title: chat主题，不超过50字
    :type title: str
    :param anonymous: chat是否匿名, defaults to False
    :type anonymous: bool, optional
    :return: 新chat的id（创建失败为-1）和表明创建chat/发送提问结果的MESSAGECONTEXT
    :rtype: Tuple[int, MESSAGECONTEXT]
    """
    if (not respondent.accept_anonymous_chat) and anonymous:
        return -1, wrong("对方目前不允许匿名提问!")
    
    # 目前提问方回答方都需要是自然人
    valid, questioner_type, _ = check_user_type(request.user)
    valid, respondent_type, _ = check_user_type(respondent)
    if questioner_type != UTYPE_PER or respondent_type != UTYPE_PER:
        return -1, wrong("目前只允许个人用户之间发起问答!")
    
    # 目前不允许一个用户向另一个用户发起超过一个“进行中”的问答
    cur_chat = Chat.objects.filter(
        questioner=request.user,
        respondent=respondent,
        status=Chat.Status.PROGRESSING,
    )
    if cur_chat.exists():
        return -1, wrong("您已经像该用户发起过进行中的问答，请先关闭之前的问答再创建新提问!")

    if len(title) > 50: # Chat.title的max_length为50
        return -1, wrong("主题长度超过50字!")
    if len(request.POST["comment"]) == 0:
        return -1, wrong("提问内容不能为空!")
    
    with transaction.atomic():
        chat = Chat.objects.create(
            questioner=request.user,
            respondent=respondent,
            title=title,
            anonymous=anonymous
        )
        # 创建chat后没有发送通知，随后创建chat的第一条comment时会发送通知
        comment_context = add_chat_message(request, chat)
    
    return chat.id, comment_context
