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
from django.db.models import Q


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
@log.except_captured(source='views[feedbackbox]', record_user=True)
def feedbackbox(request):

    valid, user_type, html_display = utils.check_user_type(request.user)

    me = get_person_or_org(request.user, user_type)

    issued_feedback = (
        Feedback.objects
        .filter(issue_status=Feedback.IssueStatus.ISSUED)
        .order_by("-feedback_time")
    )

    if user_type == "Person":
        my_feedback = issued_feedback.filter(person_id=me)
    else:
        my_feedback = issued_feedback.filter(org_id=me)

    undone_feedback = (
        my_feedback
        .filter(
            Q(solve_status=Feedback.SolveStatus.SOLVING)
            | Q(solve_status=Feedback.SolveStatus.UNMARKED)
        )
    )
    done_feedback = (
        my_feedback
        .filter(
            Q(solve_status=Feedback.SolveStatus.SOLVED)
            | Q(solve_status=Feedback.SolveStatus.UNSOLVABLE)
        )
    )

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="反馈记录")

    return render(request, "feedbackbox.html", locals())


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(source='views[pubilcFeedback]', record_user=True)
def publicFeedback(request):

    valid, user_type, html_display = utils.check_user_type(request.user)

    me = get_person_or_org(request.user, user_type)

    public_feedback = (
        Feedback.objects
        .filter(public_status=Feedback.PublicStatus.PUBLIC)
        .filter(issue_status=Feedback.IssueStatus.ISSUED)
        .order_by("-feedback_time")
    )
    academic_feedback = public_feedback.filter(type__name = "学术反馈")
    right_feedback = public_feedback.filter(type__name = "权益反馈")

    bar_display = utils.get_sidebar_and_navbar(request.user, navbar_name="留言公开")

    return render(request, "publicFeedback.html", locals())
