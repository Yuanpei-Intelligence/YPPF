from app.views_dependency import *
from app.models import (
    Organization,
    OrganizationType,
    FeedbackType,
    Feedback,
)
from app.utils import (
    get_person_or_org,
)
from app.feedback_utils import (
    update_feedback,
    make_relevant_notification,
)


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
    # TODO: 一个选择反馈类型的表单，将反馈类型传到此处！
    feedback_type = "学术反馈"

    # 根据是否有newid来判断是否是第一次
    feedback_id = request.GET.get("feedback_id", None)

    # 获取前端页面中可能存在的提示
    if request.GET.get("warn_code", None) is not None:
        html_display["warn_code"] = int(request.GET.get("warn_code"))
        html_display["warn_message"] = request.GET.get("warn_message")

    if feedback_id is not None: # 如果存在对应反馈
        try:   # 尝试读取已有的Feedback存档
            feedback = Feedback.objects.get(id=feedback_id)
            # 接下来检查是否有权限check这个条目，应该是本人/对应组织
            assert (feedback.person == me) or (feedback.org == me)
        except: #恶意跳转
            html_display["warn_code"] = 1
            html_display["warn_message"] = "您没有权限访问该网址！"
            return redirect("/welcome/" +
                            "?warn_code=1&warn_message={warn_message}".format(
                                warn_message=html_display["warn_message"]))
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
                raise NotImplementedError("返回了未知类型的post_type，请注意检查！")

        elif context["warn_code"] != 1: # 没有返回操作提示
            raise NotImplementedError("在处理反馈中出现了未预见状态，请联系管理员处理！")

        # 准备用户提示量
        html_display["warn_code"] = context["warn_code"]
        html_display["warn_message"] = context["warn_message"]
        warn_code, warn_message = context["warn_code"], context["warn_message"]

        # 为了保证稳定性，完成POST操作后同意全体回调函数，进入GET状态
        if feedback is None:
            return redirect(message_url(context, '/modifyFeedback/'))
        else:
            return redirect(message_url(context, f'/modifyFeedback/?feedback_id={feedback.id}'))

    # ———————— 完成Post操作, 接下来开始准备前端呈现 ————————

    # 首先是写死的前端量
    org_list = {
        org.oname:{
            'value'   : org.oname,
            'display' : org.oname,  # 前端呈现的使用量
            'disabled' : False,  # 是否禁止选择这个量
            'selected' : False   # 是否默认选中这个量
        }
        for org in Organization.objects.filter(
            otype_id=FeedbackType.objects.get(name=feedback_type).org_type_id
        )
    }

    # 用户写表格?
    if (is_new_feedback or (feedback.person == me and feedback.issue_status == Feedback.IssueStatus.DRAFTED)):
        allow_form_edit = True
    else:
        allow_form_edit = False

    # 用于前端展示
    feedback_person = me if is_new_feedback else feedback.person
    app_avatar_path = feedback_person.get_user_ava()
    if not is_new_feedback:
        org_list[feedback.org.oname]['selected'] = True
    bar_display = utils.get_sidebar_and_navbar(
        request.user, navbar_name="填写反馈" if is_new_feedback else "反馈详情"
    )
    return render(request, "modify_feedback.html", locals())
