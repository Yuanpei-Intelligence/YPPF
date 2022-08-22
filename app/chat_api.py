from app.views_dependency import *
from app.models import Chat
from app.chat_utils import (
    change_chat_status,
    add_chat_message,
    create_chat,
)
from boottest.global_messages import MSG_FIELD, CODE_FIELD

__all__ = [
    'startChat', 'addChatComment', 'closeChat'
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[startChat]', record_user=True)
def startChat(request: HttpRequest) -> JsonResponse:
    """
    创建新chat

    :param request: 通过ajax发来的POST请求
    :type request: HttpRequest
    :return: warn_code和warn_message
    :rtype: JsonResponse
    """
    receiver = User.objects.get(id=request.POST['receiver_id'])
    anonymous_flag = (request.POST["comment_anonymous"]=="true")
    # if (not receiver.accept_anonymous_chat) and anonymous_flag: # TODO
    #     return JsonResponse(wrong("对方不允许匿名提问!"))
    
    new_chat_id, create_chat_context = create_chat(
        request, 
        receiver, 
        request.POST['comment_title'],
        anonymous=anonymous_flag,
    )
    result_context = { 
        # 只保留warn_code和warn_message，用于前端展示；
        # 除了这两个以外还可能有create_chat_context["new_comment"]=新创建的comment对象，但它无法json化且前端应该不需要
        key: value for key, value in create_chat_context.items() 
        if key in [MSG_FIELD, CODE_FIELD]
    }
    return JsonResponse(result_context)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[addChatComment]', record_user=True)
def addChatComment(request: HttpRequest) -> JsonResponse:
    """
    给chat发送comment

    :param request: 通过ajax发来的POST请求
    :type request: HttpRequest
    :return: warn_code和warn_message
    :rtype: JsonResponse
    """
    try:
        chat = Chat.objects.get(id=request.POST.get("chat_id"))
    except:
        return JsonResponse(wrong("问答不存在!"))
    
    comment_context = add_chat_message(request, chat)
    result_context = {
        # 只保留warn_code和warn_message，用于前端展示；
        # 除了这两个以外还可能有create_chat_context["new_comment"]=新创建的comment对象，但它无法json化且前端应该不需要
        key: value for key, value in comment_context.items() 
        if key in [MSG_FIELD, CODE_FIELD]
    }
    return JsonResponse(result_context)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[closeChat]', record_user=True)
def closeChat(request: HttpRequest) -> JsonResponse:
    """
    关闭chat

    :param request: 通过ajax发来的POST请求
    :type request: HttpRequest
    :return: warn_code和warn_message
    :rtype: JsonResponse
    """
    try:
        chat = Chat.objects.get(id=request.POST.get("chat_id"))
    except:
        return JsonResponse(wrong("问答不存在!"))
    
    status_change_context = change_chat_status(chat.id, Chat.Status.CLOSED)
    result_context = {
        # 只保留warn_code和warn_message，用于前端展示；
        # 除了这两个以外应该也不会有别的了
        key: value for key, value in status_change_context.items() 
        if key in [MSG_FIELD, CODE_FIELD]
    }
    return JsonResponse(result_context)
