from app.views_dependency import *
from app.models import (
    AcademicTag,
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
from app.config import UTYPE_PER

__all__ = [
    'SearchAcademicView',
    'ShowChatsView',
    'ChatView',
    'modifyAcademic',
    'auditAcademic',
    'applyAuditAcademic',
]


class SearchAcademicView(SecureTemplateView):

    template_name = 'search_academic.html'
    # perms_required = ['app.view_naturalperson']

    def check_post(self, request: HttpRequest,
                   *args, **kwargs) -> HttpResponse | None:
        user: User = request.user  # type: ignore
        if not user.has_perm('', None):
            return self.permission_denied(request)
        if 'query' not in request.POST:
            wrong('未输入查询关键词', self.extra_context)
            return self.render(request)

    def post(self, request: HttpRequest):
        query = request.POST['query']

        self.extra_context.update({
            'query': query,
            'academic_map_list': get_search_results(query),
            'bar_display': get_sidebar_and_navbar(request.user, "学术地图搜索结果")
        })


class ShowChatsView(SecureTemplateView):

    template_name = 'showChats.html'

    def check_get(self, request: HttpRequest) -> HttpResponse | None:
        # 后续或许可以开放任意的聊天
        user: User = request.user  # type: ignore
        if not user.is_person():
            wrong('请使用个人账号访问问答中心页面!')
            return self.render(request)

    def get(self, request: HttpRequest):
        user: User = request.user  # type: ignore
        sent_chats = Chat.objects.filter(
            questioner=user).order_by("-modify_time", "-time")
        received_chats = Chat.objects.filter(
            respondent=user).order_by("-modify_time", "-time")
        self.extra_context.update({
            'bar_display': get_sidebar_and_navbar(request.user, "学术地图问答"),
            'sent_chats': chats2Display(sent_chats, sent=True),
            'received_chats': chats2Display(received_chats, sent=False)
        })


class ChatView(SecureTemplateView):
    """Draft
    """

    template_name = 'viewChat.html'

    def check_get(self, request: HttpRequest, chat_id: str):  # type: ignore
        possible_chat = Chat.objects.filter(id=int(chat_id)).first()
        if possible_chat is None:
            wrong('问答不存在', self.extra_context)
            return self.render(request)
        chat: Chat = possible_chat
        if request.user not in [chat.questioner, chat.respondent]:
            wrong('您只能访问自己参与的问答!', self.extra_context)
            return self.render(request)
        self.chat = chat

    def get(self, request: HttpRequest, chat_id: str):
        user: User = request.user  # type: ignore
        comments2Display(self.chat, self.extra_context, user)
        self.extra_context['bar_display'] = get_sidebar_and_navbar(
            user, '学术地图问答')


class ModifyAcademicView(SecureTemplateView):

    template_name = 'modify_academic.html'

    def check_get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse | None:
        return super().check_get(request, *args, **kwargs)

    def check_post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse | None:
        return super().check_post(request, *args, **kwargs)

    def get(self, request: HttpRequest) -> HttpResponse:
        pass

    def post(self, request: HttpRequest) -> HttpResponse:
        pass

    def get_context_data(self, request: HttpRequest, **kwargs) -> Dict[str, Any] | None:
        return super().get_context_data(request, **kwargs)


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
        major_list=get_js_tag_list(me, AcademicTag.Type.MAJOR, selected=False),
        minor_list=get_js_tag_list(me, AcademicTag.Type.MINOR, selected=False),
        double_degree_list=get_js_tag_list(
            me, AcademicTag.Type.DOUBLE_DEGREE, selected=False),
        project_list=get_js_tag_list(
            me, AcademicTag.Type.PROJECT, selected=False),
    )

    # 获取用户已有的专业/项目的列表，用于select的默认选中项
    frontend_dict.update(
        selected_major_list=get_js_tag_list(
            me, AcademicTag.Type.MAJOR, selected=True),
        selected_minor_list=get_js_tag_list(
            me, AcademicTag.Type.MINOR, selected=True),
        selected_double_degree_list=get_js_tag_list(
            me, AcademicTag.Type.DOUBLE_DEGREE, selected=True),
        selected_project_list=get_js_tag_list(
            me, AcademicTag.Type.PROJECT, selected=True),
    )

    # 获取用户已有的TextEntry的contents，用于TextEntry填写栏的前端预填写
    scientific_research_list = get_text_list(
        me, AcademicTextEntry.Type.SCIENTIFIC_RESEARCH
    )
    challenge_cup_list = get_text_list(
        me, AcademicTextEntry.Type.CHALLENGE_CUP
    )
    internship_list = get_text_list(
        me, AcademicTextEntry.Type.INTERNSHIP
    )
    scientific_direction_list = get_text_list(
        me, AcademicTextEntry.Type.SCIENTIFIC_DIRECTION
    )
    graduation_list = get_text_list(
        me, AcademicTextEntry.Type.GRADUATION
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
    major_status = get_tag_status(me, AcademicTag.Type.MAJOR)
    minor_status = get_tag_status(me, AcademicTag.Type.MINOR)
    double_degree_status = get_tag_status(me, AcademicTag.Type.DOUBLE_DEGREE)
    project_status = get_tag_status(me, AcademicTag.Type.PROJECT)
    scientific_research_status = get_text_status(
        me, AcademicTextEntry.Type.SCIENTIFIC_RESEARCH
    )
    challenge_cup_status = get_text_status(
        me, AcademicTextEntry.Type.CHALLENGE_CUP
    )
    internship_status = get_text_status(
        me, AcademicTextEntry.Type.INTERNSHIP
    )
    scientific_direction_status = get_text_status(
        me, AcademicTextEntry.Type.SCIENTIFIC_DIRECTION
    )
    graduation_status = get_text_status(
        me, AcademicTextEntry.Type.GRADUATION
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
    frontend_dict["bar_display"] = get_sidebar_and_navbar(
        request.user, "修改学术地图")
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
    if not (person.get_type() == UTYPE_PER and person.is_teacher()):
        return redirect(message_url(wrong('只有教师账号可进入学术地图审核页面!')))

    frontend_dict = {}
    frontend_dict["bar_display"] = get_sidebar_and_navbar(
        request.user, "审核学术地图")
    frontend_dict["student_list"] = get_wait_audit_student()

    return render(request, "audit_academic.html", frontend_dict)


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[applyAuditAcademic]', record_user=True)
def applyAuditAcademic(request: HttpRequest):
    if not NaturalPerson.objects.get_by_user(request.user).is_teacher():
        return JsonResponse(wrong("只有老师才能执行审核操作！"))
    try:
        author = NaturalPerson.objects.get(
            person_id_id=request.POST.get("author_id"))
        # 需要回传作者的person_id.id
        audit_academic_map(author)
        return JsonResponse(succeed("审核成功！"))
    except:
        return JsonResponse(wrong("审核发布时发生未知错误，请联系管理员！"))
