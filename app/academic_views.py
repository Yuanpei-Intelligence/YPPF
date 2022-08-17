from app.views_dependency import *
from app.models import (
    AcademicTagEntry,
    AcademicTextEntry,
    Chat,
)
from app.academic_utils import (
    get_search_results,
    change_chat_status,
    add_chat_message,
    chats2Display,
    comments2Display,
)
from app.utils import get_sidebar_and_navbar

__all__ = [
    'searchAcademic', 'showChats', 'viewChat'
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[searchAcademic]', record_user=True)
def searchAcademic(request: HttpRequest) -> HttpResponse:
    """
    学术地图的搜索结果界面

    :param request: http请求
    :type request: HttpRequest
    :return: http响应
    :rtype: HttpResponse
    """
    frontend_dict = {}
    
    # POST表明搜索框发起检索
    if request.method == "POST" and request.POST:  
        query = request.POST["query"]   # 获取用户输入的关键词
        frontend_dict["query"] = query  # 前端可借此将字体设置为高亮
        frontend_dict["academic_map_list"] = get_search_results(query)
        
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "学术地图搜索结果")
    return render(request, "search_academic.html", frontend_dict)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[showChats]', record_user=True)
def showChats(request: HttpRequest) -> HttpResponse:
    """
    （学术地图）问答中心页面
    展示我发出的和发给我的所有chat；可以关闭进行中的问答

    :param request: 进入问答中心页面的request
    :type request: HttpRequest
    :return: 问答中心页面
    :rtype: HttpResponse
    """
    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "学术地图问答")

    if request.method == "POST" and request.POST:
        if request.POST.get('close_chat', '') != '': # 关闭单个问答
            chat_id = int(request.POST['close_chat'])
            context = change_chat_status(chat_id, to_status=Chat.Status.CLOSED) # 会给出warn_message
            my_messages.transfer_message_context(
                context, frontend_dict, normalize=False)
        # elif request.POST.get('comment_submit', '') != '': # 对某个问答新增评论。本页面不再支持此功能，挪到viewChat
        #     chat_id = int(request.POST['comment_submit'])
        #     context = add_chat_message(request, chat_id)
        #     my_messages.transfer_message_context(context, frontend_dict, normalize=False)
    
    # 获取我发出的和发给我的所有chat
    sent_chats = Chat.objects.filter(
        questioner=request.user).order_by("-modify_time", "-time")
    received_chats = Chat.objects.filter(
        respondent=request.user).order_by("-modify_time", "-time")
    frontend_dict["sent_chats"] = chats2Display(sent_chats, sent=True)
    frontend_dict["received_chats"] = chats2Display(received_chats, sent=False) # chats2Display返回两个列表，分别是进行中的和其他
    
    return render(request, "showChats.html", frontend_dict)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[viewChat]', record_user=True)
def viewChat(request: HttpRequest, chat_id: str) -> HttpResponse:
    """
    （学术地图）问答详情页面

    :param request: 进入问答详情页面的request
    :type request: HttpRequest
    :param chat_id: 当前问答的id
    :type chat_id: str
    :return: 问答详情页面
    :rtype: HttpResponse
    """
    try:
        chat_id = int(chat_id)
        chat = Chat.objects.get(id=chat_id)
    except:
        return redirect(message_url(wrong('问答不存在!')))
    if chat.questioner != request.user and chat.respondent != request.user:
        return redirect(message_url(wrong('您只能访问自己参与的问答!')))
    
    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "学术地图问答")

    if request.method == "POST" and request.POST:
        if request.POST.get('close', '') == '1': # 关闭当前问答
            status_change_context = change_chat_status(chat.id, Chat.Status.CLOSED)
            my_messages.transfer_message_context(status_change_context, frontend_dict, normalize=False)
            chat = Chat.objects.get(id=chat_id) # 数据库中状态修改了，需要重新取一遍
        elif request.POST.get('comment_submit', '') == '1': # 发消息
            comment_context = add_chat_message(request, chat)
            my_messages.transfer_message_context(comment_context, frontend_dict, normalize=False)
    
    comments2Display(chat, frontend_dict, request.user) # 把包括chat中的所有comments在内的前端所需的各种信息填入frontend_dict
    
    return render(request, "viewChat.html", frontend_dict)
