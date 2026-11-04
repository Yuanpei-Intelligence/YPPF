from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST

from app import utils
from app.models import Participation, ParticipationStory, PersonProfileTag, ProfileTag
from app.profile_forms import (
    ActivityStoryCommentForm,
    ProfileStoryForm,
    ProfileTagUpdateForm,
)
from app.profile_utils import (
    add_tag_story_comment,
    activity_story_is_public,
    add_activity_story_comment,
    build_activity_story_page,
    build_skill_story_page,
    delete_activity_story,
    replace_person_profile_tags,
    tag_story_is_public,
    toggle_activity_story_like,
    toggle_tag_story_like,
    update_activity_story,
    update_tag_story,
)
from app.utils import get_classified_user
from app.view.base import ProfileTemplateView
from app.views_dependency import logger
from utils.global_messages import append_query


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def updateProfileTags(request):
    """Replace the current person's public interest and skill tags."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以编辑个人画像标签。")

    person = get_classified_user(request.user)
    form = ProfileTagUpdateForm(request.POST)
    if not form.is_valid():
        request.session["profile_tag_errors"] = form.errors.get_json_data()
        return redirect(append_query(person.get_absolute_url(), tags="invalid"))

    try:
        replace_person_profile_tags(
            person=person,
            interest_tags=form.cleaned_data["interest_tags"],
            skill_tags=form.cleaned_data["skill_tags"],
            custom_tags=form.cleaned_data["custom_tags"],
        )
    except ValidationError as exc:
        request.session["profile_tag_errors"] = {
            "__all__": [{"message": message, "code": "invalid"} for message in exc.messages]
        }
        return redirect(append_query(person.get_absolute_url(), tags="invalid"))

    return redirect(append_query(person.get_absolute_url(), tags="success"))


def _story_error_redirect(request, person, form_or_exception):
    if isinstance(form_or_exception, ValidationError):
        errors = {
            "__all__": [
                {"message": message, "code": "invalid"}
                for message in form_or_exception.messages
            ]
        }
    else:
        errors = form_or_exception.errors.get_json_data()
    request.session["profile_story_errors"] = errors
    return redirect(append_query(person.get_absolute_url(), story="invalid"))


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def updateTagStory(request, selection_id):
    """Update one owned tag note and its bounded image collection."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以编辑画像说明。")
    person = get_classified_user(request.user)
    selection = get_object_or_404(
        PersonProfileTag.objects.filter(
            person=person, tag__status=ProfileTag.Status.VISIBLE
        ).prefetch_related("images"),
        pk=selection_id,
    )
    form = ProfileStoryForm(
        request.POST,
        request.FILES,
        existing_images=selection.images.all(),
    )
    if not form.is_valid():
        return _story_error_redirect(request, person, form)
    try:
        update_tag_story(
            person=person,
            selection=selection,
            description=form.cleaned_data["description"],
            uploaded_images=form.cleaned_data["images"],
            delete_image_ids=form.cleaned_data["delete_image_ids"],
        )
    except ValidationError as exc:
        return _story_error_redirect(request, person, exc)
    return redirect(append_query(person.get_absolute_url(), story="success"))


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def updateActivityStory(request, participation_id):
    """Update one owned eligible activity note and its images."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以编辑活动记录。")
    person = get_classified_user(request.user)
    participation = get_object_or_404(
        Participation.objects.filter(person=person), pk=participation_id
    )
    try:
        story = participation.story
        existing_images = story.images.all()
    except ParticipationStory.DoesNotExist:
        existing_images = ()
    form = ProfileStoryForm(
        request.POST,
        request.FILES,
        existing_images=existing_images,
    )
    if not form.is_valid():
        return _story_error_redirect(request, person, form)
    try:
        update_activity_story(
            person=person,
            participation=participation,
            description=form.cleaned_data["description"],
            uploaded_images=form.cleaned_data["images"],
            delete_image_ids=form.cleaned_data["delete_image_ids"],
        )
    except ValidationError as exc:
        return _story_error_redirect(request, person, exc)
    return redirect(append_query(person.get_absolute_url(), story="success"))


def _story_redirect(request, owner, status, default_fragment="#activity-album"):
    if status:
        request.session["profile_album_message"] = status
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(append_query(owner.get_absolute_url(), album="updated") + default_fragment)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CommunityBoard(ProfileTemplateView):
    """Newest-first activity or interest/skill uploads shared across profiles."""

    http_method_names = ["get"]
    template_name = "community/board.html"
    page_name = "社区看板"

    def setup(self, request, *args, **kwargs):
        self.board = kwargs["board"]
        return super().setup(request, *args, **kwargs)

    def prepare_get(self):
        if self.board not in {"activities", "skills"}:
            return self.permission_denied("看板不存在")
        return self.get

    def get(self):
        viewer_person = (
            get_classified_user(self.request.user)
            if self.request.user.is_person()
            else None
        )
        if self.board == "activities":
            feed_page = build_activity_story_page(
                viewer_person=viewer_person,
                page_number=self.request.GET.get("page", 1),
            )
            board_title = "近期活动动态"
            board_description = "同学们最近上传或更新的活动图文记录"
        else:
            feed_page = build_skill_story_page(
                viewer_person=viewer_person,
                page_number=self.request.GET.get("page", 1),
            )
            board_title = "近期兴趣与技能动态"
            board_description = "同学们最近填写或分享的兴趣、技能与图文经验"
        return self.render(
            board=self.board,
            board_title=board_title,
            board_description=board_description,
            feed_page=feed_page,
            return_path=self.request.get_full_path(),
            interaction_message=self.request.session.pop(
                "profile_album_message", ""
            ),
        )


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def toggleActivityStoryLike(request, story_id):
    """Toggle the current natural person's like on one public activity story."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以点赞活动记录。")
    person = get_classified_user(request.user)
    story = get_object_or_404(
        ParticipationStory.objects.select_related("participation__person"),
        pk=story_id,
    )
    if not activity_story_is_public(story):
        return HttpResponseForbidden("该活动记录当前不可见。")
    try:
        liked = toggle_activity_story_like(person=person, story=story)
    except ValidationError as exc:
        return _story_redirect(request, story.participation.person, exc.messages[0])
    message = "已点赞。" if liked else "已取消点赞。"
    return _story_redirect(request, story.participation.person, message)


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def addActivityStoryComment(request, story_id):
    """Add an immediately public plain-text comment to an activity story."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以评论活动记录。")
    person = get_classified_user(request.user)
    story = get_object_or_404(
        ParticipationStory.objects.select_related("participation__person"),
        pk=story_id,
    )
    if not activity_story_is_public(story):
        return HttpResponseForbidden("该活动记录当前不可见。")
    form = ActivityStoryCommentForm(request.POST)
    if not form.is_valid():
        message = next(iter(form.errors.values()))[0]
        return _story_redirect(request, story.participation.person, message)
    try:
        add_activity_story_comment(
            person=person,
            story=story,
            content=form.cleaned_data["content"],
        )
    except ValidationError as exc:
        return _story_redirect(request, story.participation.person, exc.messages[0])
    return _story_redirect(request, story.participation.person, "评论已发布。")


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def toggleTagStoryLike(request, selection_id):
    """Toggle the current person's like on a public interest or skill story."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以点赞兴趣或技能记录。")
    person = get_classified_user(request.user)
    selection = get_object_or_404(
        PersonProfileTag.objects.select_related("person", "tag", "tag__category"),
        pk=selection_id,
    )
    if not tag_story_is_public(selection):
        return HttpResponseForbidden("该兴趣或技能记录当前不可见。")
    try:
        liked = toggle_tag_story_like(person=person, selection=selection)
    except ValidationError as exc:
        return _story_redirect(
            request, selection.person, exc.messages[0], "#tag-story-interactions"
        )
    message = "已点赞。" if liked else "已取消点赞。"
    return _story_redirect(
        request, selection.person, message, "#tag-story-interactions"
    )


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def addTagStoryComment(request, selection_id):
    """Add a public plain-text comment to an interest or skill story."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以评论兴趣或技能记录。")
    person = get_classified_user(request.user)
    selection = get_object_or_404(
        PersonProfileTag.objects.select_related("person", "tag", "tag__category"),
        pk=selection_id,
    )
    if not tag_story_is_public(selection):
        return HttpResponseForbidden("该兴趣或技能记录当前不可见。")
    form = ActivityStoryCommentForm(request.POST)
    if not form.is_valid():
        message = next(iter(form.errors.values()))[0]
        return _story_redirect(
            request, selection.person, message, "#tag-story-interactions"
        )
    try:
        add_tag_story_comment(
            person=person,
            selection=selection,
            content=form.cleaned_data["content"],
        )
    except ValidationError as exc:
        return _story_redirect(
            request, selection.person, exc.messages[0], "#tag-story-interactions"
        )
    return _story_redirect(
        request, selection.person, "评论已发布。", "#tag-story-interactions"
    )


@csrf_protect
@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@require_POST
@logger.secure_view()
def deleteActivityStory(request, story_id):
    """Delete one activity story owned by the current natural person."""

    if not request.user.is_person():
        return HttpResponseForbidden("只有个人账户可以删除活动记录。")
    person = get_classified_user(request.user)
    story = get_object_or_404(
        ParticipationStory.objects.select_related("participation"),
        pk=story_id,
        participation__person=person,
    )
    delete_activity_story(person=person, story=story)
    return _story_redirect(request, person, "活动记录已删除。")
