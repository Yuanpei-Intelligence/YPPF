from app.views_dependency import *
from app.models import (
    AcademicTag,
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,
    Chat,
    NaturalPerson,
)
from app.academic_utils import (
    get_search_results,
    chats2Display,
    comments2Display,
    get_js_tag_list,
    get_text_list,
    get_tag_status,
    get_text_status,
    update_academic_map,
    get_wait_audit_student,
    audit_academic_map,
)
from app.utils import (
    check_user_type, 
    get_sidebar_and_navbar,
    get_person_or_org,
)
from app.constants import UTYPE_PER

__all__ = [
    'searchAcademic', 
    'showChats', 
    'viewChat',
    'modifyAcademic',
    'auditAcademic',
    'applyAuditAcademic',
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


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[modifyAcademic]', record_user=True)
def modifyAcademic(request: HttpRequest) -> HttpResponse:
    """
    学术地图编辑界面

    :param request: http请求
    :type request: HttpRequest
    :return: http响应
    :rtype: HttpResponse
    """
    frontend_dict = {}
    
    _, user_type, _ = check_user_type(request.user)
    if user_type != UTYPE_PER:  # 只允许个人账户修改学术地图
        return redirect(message_url(wrong("只有个人才可以修改自己的学术地图！")))

    # POST表明编辑界面发起修改
    if request.method == "POST" and request.POST:
        try:
            context = update_academic_map(request)
            if context["warn_code"] == 1:    # 填写的TextEntry太长导致填写失败
                return redirect(message_url(context, "/modifyAcademic/"))
            else:                            # warn_code == 2，表明填写成功
                return redirect(message_url(context, "/stuinfo/#tab=academic_map"))
        except:
            return redirect(message_url(wrong("修改过程中出现意料之外的错误，请联系工作人员处理！")))
    
    # 不是POST，说明用户希望编辑学术地图，下面准备前端展示量
    # 获取所有专业/项目的列表，左右前端select框的下拉选项
    me = get_person_or_org(request.user, UTYPE_PER)
    frontend_dict.update(
        major_list=get_js_tag_list(me, AcademicTag.AcademicTagType.MAJOR, selected=False),
        minor_list=get_js_tag_list(me, AcademicTag.AcademicTagType.MINOR, selected=False),
        double_degree_list=get_js_tag_list(me, AcademicTag.AcademicTagType.DOUBLE_DEGREE, selected=False),
        project_list=get_js_tag_list(me, AcademicTag.AcademicTagType.PROJECT, selected=False),
    )
    
    # 获取用户已有的专业/项目的列表，用于select的默认选中项
    frontend_dict.update(
        selected_major_list=get_js_tag_list(me, AcademicTag.AcademicTagType.MAJOR, selected=True),
        selected_minor_list=get_js_tag_list(me, AcademicTag.AcademicTagType.MINOR, selected=True),
        selected_double_degree_list=get_js_tag_list(me, AcademicTag.AcademicTagType.DOUBLE_DEGREE, selected=True),
        selected_project_list=get_js_tag_list(me, AcademicTag.AcademicTagType.PROJECT, selected=True),
    )
    
    # 获取用户已有的TextEntry的contents，用于TextEntry填写栏的前端预填写
    scientific_research_list = get_text_list(
        me, AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH
    )
    challenge_cup_list = get_text_list(
        me, AcademicTextEntry.AcademicTextType.CHALLENGE_CUP
    )
    internship_list = get_text_list(
        me, AcademicTextEntry.AcademicTextType.INTERNSHIP
    )
    scientific_direction_list = get_text_list(
        me, AcademicTextEntry.AcademicTextType.SCIENTIFIC_DIRECTION
    )
    graduation_list = get_text_list(
        me, AcademicTextEntry.AcademicTextType.GRADUATION
    )
    frontend_dict.update(
        scientific_research_list=scientific_research_list,
        challenge_cup_list=challenge_cup_list,
        internship_list=internship_list,
        scientific_direction_list=scientific_direction_list,
        graduation_list=graduation_list,
        scientific_research_num=len(scientific_research_list),
        challenge_cup_num=len(challenge_cup_list),
        internship_num=len(internship_list),
        scientific_direction_num=len(scientific_direction_list),
        graduation_num=len(graduation_list),
    )
    
    # 最后获取每一种atype对应的entry的公开状态，如果没有则默认为公开
    major_status = get_tag_status(me, AcademicTag.AcademicTagType.MAJOR)
    minor_status = get_tag_status(me, AcademicTag.AcademicTagType.MINOR)
    double_degree_status = get_tag_status(me, AcademicTag.AcademicTagType.DOUBLE_DEGREE)
    project_status = get_tag_status(me, AcademicTag.AcademicTagType.PROJECT)
    scientific_research_status = get_text_status(
        me, AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH
    )
    challenge_cup_status = get_text_status(
        me, AcademicTextEntry.AcademicTextType.CHALLENGE_CUP
    )
    internship_status = get_text_status(
        me, AcademicTextEntry.AcademicTextType.INTERNSHIP
    )
    scientific_direction_status = get_text_status(
        me, AcademicTextEntry.AcademicTextType.SCIENTIFIC_DIRECTION
    )
    graduation_status = get_text_status(
        me, AcademicTextEntry.AcademicTextType.GRADUATION
    )
    
    status_dict = dict(
        major_status=major_status,
        minor_status=minor_status,
        double_degree_status=double_degree_status,
        project_status=project_status,
        scientific_research_status=scientific_research_status,
        challenge_cup_status=challenge_cup_status,
        internship_status=internship_status,
        scientific_direction_status=scientific_direction_status,
        graduation_status=graduation_status,
    )
    frontend_dict.update(status_dict)
    
    # 获取“全部公开”checkbox的选中状态与公开的type数量/总type数
    frontend_dict["all_status"] = "私密" if "私密" in status_dict.values() else "公开"
    frontend_dict["public_num"] = list(status_dict.values()).count("公开")
    frontend_dict["total_num"] = len(status_dict)
    
    # 获取用户是否允许他人提问
    frontend_dict["accept_chat"] = request.user.accept_chat
    
    # 最后获取侧边栏信息
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "修改学术地图")
    frontend_dict["warn_code"] = request.GET.get('warn_code', 0)
    frontend_dict["warn_message"] = request.GET.get('warn_message', "")
    return render(request, "modify_academic.html", frontend_dict)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[auditAcademic]', record_user=True)
def auditAcademic(request: HttpRequest) -> HttpResponse:
    """
    供教师使用的页面，展示所有待审核的学术地图

    :param request
    :type request: HttpRequest
    :return
    :rtype: HttpResponse
    """
    # 身份检查
    person = get_person_or_org(request.user)
    if not person.is_teacher():
        return redirect(message_url(wrong('只有教师账号可进入学术地图审核页面!')))

    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "审核学术地图")
    frontend_dict["student_list"] = get_wait_audit_student()
    
    return render(request, "audit_academic.html", frontend_dict)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[applyAuditAcademic]', record_user=True)
def applyAuditAcademic(request: HttpRequest):
    author = NaturalPerson.objects.get(person_id_id=request.POST.get("author_id"))
    # 需要回传作者的person_id.id
    audit_academic_map(author)
    return JsonResponse({})

