from app.views_dependency import *
from app.models import (
    Organization,
    OrganizationType,

    Feedback,
    FeedbackType,
)
from app.utils import (
    get_person_or_org,
)
from app.feedback_utils import (
    update_feedback,
    make_relevant_notification,
)

__all__ = [
    'feedbackWelcome',
    'modifyFeedback',
]


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='feedback_views[feedbackWelcome]', record_user=True)
def feedbackWelcome(request):
    '''
    【我要留言】的初始化页面，呈现反馈提醒、选择反馈类型
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)
    my_messages.transfer_message_context(request.GET, html_display)

    feedback_type_list = list(FeedbackType.objects.all())
    
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="我要留言"
    )
    return render(request, "feedback_welcome.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='feedback_views[modifyFeedback]', record_user=True)
def modifyFeedback(request):
    '''
    反馈表单填写、修改与提交的视图函数
    '''
    valid, user_type, html_display = utils.check_user_type(request.user)
    me = get_person_or_org(request.user)
    
    # 设置feedback为None, 如果非None则自动覆盖
    feedback = None

    # 根据是否有newid来判断是否是第一次
    feedback_id = request.GET.get("feedback_id")

    # 获取前端页面中可能存在的提示
    my_messages.transfer_message_context(request.GET, html_display)

    if feedback_id is not None: # 如果存在对应反馈
        try:   # 尝试读取已有的Feedback存档
            feedback = Feedback.objects.get(id=feedback_id)
            # 接下来检查是否有权限check这个条目，应该是本人/对应组织
            assert (feedback.person == me) or (feedback.org == me)
        except: #恶意跳转
            return redirect(message_url(wrong("您没有权限访问该网址！")))
        is_new_feedback = False # 前端使用量, 表示是已有的反馈还是新的

    else:
        # 如果不存在id, 是一个新建反馈页面。
        feedback = None
        is_new_feedback = True

    '''
        至此，如果是新反馈那么feedback为None，否则为对应反馈
        feedback = None只有在个人新建反馈的时候才可能出现，对应为is_new_feedback
        接下来POST
    '''

    if request.method == "POST":
        context = update_feedback(feedback, me, request)

        if context["warn_code"] == 2:   # 成功修改
            feedback = Feedback.objects.get(id=context["feedback_id"])
            is_new_application = False  # 状态变更
            # 处理通知相关的操作
            try:
                feasible_post = [
                    "directly_submit",
                    "submit_draft",
                ]
                if request.POST.get('post_type') in feasible_post:
                    make_relevant_notification(feedback, request.POST, me)
            except:
                return redirect(message_url(
                                wrong("返回了未知类型的post_type，请注意检查！"),
                                request.path))

        elif context["warn_code"] != 1: # 没有返回操作提示
            return redirect(message_url(
                            wrong("在处理反馈中出现了未预见状态，请联系管理员处理！"),
                            request.path))

        # 准备用户提示量
        my_messages.transfer_message_context(context, html_display)

        # 为了保证稳定性，完成POST操作后同意全体回调函数，进入GET状态
        if feedback is None:
            return redirect(message_url(context, '/modifyFeedback/'))
        elif feedback.issue_status == Feedback.IssueStatus.DRAFTED:
            return redirect(message_url(context, f'/modifyFeedback/?feedback_id={feedback.id}'))
        else: # 发布，feedback.issue_status == Feedback.IssueStatus.ISSUED
            return redirect(message_url(context, f'/viewFeedback/feedback_id={feedback.id}'))

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    feedback_type_list = {
        fbtype.name:{
            'value'   : fbtype.name,
            'display' : fbtype.name,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for fbtype in FeedbackType.objects.all()
    }
    
    org_type_list = {
        otype.otype_name:{
            'value'   : otype.otype_name,
            'display' : otype.otype_name,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for otype in OrganizationType.objects.all()
    }
    
    org_list = {
        org.oname:{
            'value'   : org.oname,
            'display' : org.oname,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for org in Organization.objects.all()
    }

    org_type_list[''] = {
        'value': '', 'display': '', 'disabled': False, 'selected': False,
    }
    org_list[''] = {
        'value': '', 'display': '', 'disabled': False, 'selected': False,
    }

    # 用户写表格?
    if (is_new_feedback or (feedback.person == me and feedback.issue_status == Feedback.IssueStatus.DRAFTED)):
        allow_form_edit = True
    else:
        allow_form_edit = False

    # 用于前端展示
    feedback_person = me if is_new_feedback else feedback.person
    app_avatar_path = feedback_person.get_user_ava()
    all_org_types = [otype.otype_name for otype in OrganizationType.objects.all()]
    all_org_list = []
    for otype in all_org_types:
        all_org_list.append(([otype,] +
            [org.oname for org in Organization.objects.filter(
                otype=OrganizationType.objects.get(otype_name=otype)
            )]) if otype != '' else ([otype,] + [
                org.oname for org in Organization.objects.all()
            ])
        )
    fbtype_to_org = [] #存有多个列表，每个列表为[fbtype, orgtype, org]，用于前端变换下拉选项
    for fbtype in feedback_type_list.keys():
        fbtype_obj = FeedbackType.objects.get(name=fbtype)
        fbtype_to_org.append([fbtype,] + ([
            fbtype_obj.org_type.otype_name,
        ] if fbtype_obj.org_type else ['',]) + ([
            fbtype_obj.org.oname,
        ] if fbtype_obj.org else ['',])
        )
    if not is_new_feedback:
        feedback_type_list[feedback.type.name]['selected'] = True
        if feedback.org_type is not None:
            org_type_list[feedback.org_type.otype_name]['selected'] = True
            for org in Organization.objects.exclude(
                    otype=OrganizationType.objects.get(
                        otype_name=feedback.org_type.otype_name)
                    ):
                org_list[org.oname]['disabled'] = True
        else:
            org_type_list['']['selected'] = True
            for org in org_list.keys():
                org_list[org]['disabled'] = True
        if feedback.org is not None:
            org_list[feedback.org.oname]['selected'] = True
        else:
            org_list['']['selected'] = True
    else: # feedback_type 默认选中“35楼生活权益反馈”，默认选中项将在前端实时更新。
        feedback_type = "35楼生活权益反馈"
        if FeedbackType.objects.get(name=feedback_type).org_type is not None:
            org_type_list[
                FeedbackType.objects.get(name=feedback_type).org_type.otype_name
            ]['selected'] = True
            for org in Organization.objects.exclude(
                    otype=OrganizationType.objects.get(
                        otype_name=FeedbackType.objects.get(name=feedback_type).org_type.otype_name)
                    ):
                org_list[org.oname]['disabled'] = True
        else:
            org_type_list['']['selected'] = True
            for org in org_list.keys():
                org_list[org]['disabled'] = True
        if FeedbackType.objects.get(name=feedback_type).org is not None:
            org_list[
                FeedbackType.objects.get(name=feedback_type).org.oname
            ]['selected'] = True
        else:
            org_list['']['selected'] = True
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="填写反馈" if is_new_feedback else "反馈详情"
    )
    return render(request, "modify_feedback.html", locals())
