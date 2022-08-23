from app.views_dependency import *
from app.models import (
    AcademicTagEntry,
    AcademicTextEntry,
    Chat,
)
from app.academic_utils import (
    get_search_results,
    chats2Display,
    comments2Display,
)
from app.utils import get_sidebar_and_navbar, check_user_type

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
    valid, user_type, _ = check_user_type(request.user)
    if user_type != UTYPE_PER:
        return redirect(message_url(wrong('请使用个人账号访问问答中心页面!')))
    
    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "学术地图问答")

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
    comments2Display(chat, frontend_dict, request.user) # 把包括chat中的所有comments在内的前端所需的各种信息填入frontend_dict
    
    return render(request, "viewChat.html", frontend_dict)
