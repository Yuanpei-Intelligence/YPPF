from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q

from app.models import (
    AcademicTagEntry,
    AcademicTextEntry,
    CourseRecord,
    NaturalPerson,
    Participation,
    ParticipationStory,
    ParticipationStoryComment,
    ParticipationStoryImage,
    ParticipationStoryLike,
    PersonProfileTag,
    PersonProfileTagComment,
    PersonProfileTagImage,
    PersonProfileTagLike,
    Position,
    ProfileTag,
    ProfileTagCategory,
)

from app.profile_forms import MAX_STORY_IMAGES


def _active_category_tree():
    categories = list(
        ProfileTagCategory.objects.filter(is_active=True).order_by("sort_order", "id")
    )
    by_parent = defaultdict(list)
    for category in categories:
        by_parent[category.parent_id].append(category)

    active_nodes = []

    def build(category):
        node = {"id": category.pk, "name": category.name, "children": [], "tags": []}
        active_nodes.append(category.pk)
        node["children"] = [build(child) for child in by_parent[category.pk]]
        return node

    roots = [build(category) for category in by_parent[None]]
    return roots, active_nodes


def _candidate_tree(kind, selected_tag_ids):
    tree, active_category_ids = _active_category_tree()
    nodes_by_id = {}

    def index_nodes(nodes):
        for node in nodes:
            nodes_by_id[node["id"]] = node
            index_nodes(node["children"])

    index_nodes(tree)
    official_tags = ProfileTag.objects.filter(
        category_id__in=active_category_ids,
        source=ProfileTag.Source.OFFICIAL,
        status=ProfileTag.Status.VISIBLE,
        applies_to__in=[kind, ProfileTag.AppliesTo.BOTH],
    ).order_by("name", "id")
    for tag in official_tags:
        nodes_by_id[tag.category_id]["tags"].append(
            {"id": tag.pk, "name": tag.name, "selected": tag.pk in selected_tag_ids}
        )

    def prune(nodes):
        result = []
        for node in nodes:
            node["children"] = prune(node["children"])
            if node["tags"] or node["children"]:
                result.append(node)
        return result

    return prune(tree)


def build_profile_context(
    person: NaturalPerson,
    is_myself: bool,
    viewer_person: NaturalPerson | None = None,
    album_page_number=1,
):
    tree, active_category_ids = _active_category_tree()
    selections = list(
        PersonProfileTag.objects.filter(
            person=person,
            tag__status=ProfileTag.Status.VISIBLE,
            tag__category_id__in=active_category_ids,
        ).select_related("tag", "tag__category").prefetch_related(
            "images",
            "likes",
            Prefetch(
                "story_comments",
                queryset=PersonProfileTagComment.objects.filter(
                    status=PersonProfileTagComment.Status.VISIBLE
                ).select_related("author", "author__person_id"),
            ),
        )
    )
    for selection in selections:
        selection.display_description = (
            selection.description
            if is_myself
            or selection.description_status
            == PersonProfileTag.ContentStatus.VISIBLE
            else ""
        )
        selection.display_images = [
            image
            for image in selection.images.all()
            if is_myself or image.status == PersonProfileTagImage.Status.VISIBLE
        ]
        prepare_tag_story(selection, viewer_person)
    interest_tag_ids = {
        selection.tag_id
        for selection in selections
        if selection.kind == PersonProfileTag.Kind.INTEREST
    }
    skill_tag_ids = {
        selection.tag_id
        for selection in selections
        if selection.kind == PersonProfileTag.Kind.SKILL
    }

    custom_interest_tags = [
        selection.tag
        for selection in selections
        if selection.kind == PersonProfileTag.Kind.INTEREST
        and selection.tag.source == ProfileTag.Source.CUSTOM
    ]
    custom_skill_tags = [
        selection.tag
        for selection in selections
        if selection.kind == PersonProfileTag.Kind.SKILL
        and selection.tag.source == ProfileTag.Source.CUSTOM
    ]

    eligible_statuses = [
        Participation.AttendStatus.APPLYSUCCESS,
        Participation.AttendStatus.ATTENDED,
    ]
    eligible_participations = Participation.objects.filter(
        person=person,
        status__in=eligible_statuses,
    ).select_related(
        "activity", "activity__organization_id", "story"
    ).prefetch_related(
        Prefetch("story__images", queryset=ParticipationStoryImage.objects.all())
    )
    recent_activities = list(eligible_participations.order_by("-activity__start")[:8])
    for participation in recent_activities:
        prepare_participation_story(participation, is_myself)

    album_stories = ParticipationStory.objects.filter(
        participation__person=person,
        participation__status__in=eligible_statuses,
    ).filter(Q(description__gt="") | Q(images__isnull=False))
    if not is_myself:
        album_stories = album_stories.filter(
            Q(
                description_status=ParticipationStory.ContentStatus.VISIBLE,
                description__gt="",
            )
            | Q(images__status=ParticipationStoryImage.Status.VISIBLE)
        )
    album_stories = (
        album_stories.select_related(
            "participation",
            "participation__activity",
            "participation__activity__organization_id",
        )
        .prefetch_related(
            "images",
            "likes",
            Prefetch(
                "story_comments",
                queryset=ParticipationStoryComment.objects.filter(
                    status=ParticipationStoryComment.Status.VISIBLE
                ).select_related("author", "author__person_id"),
            ),
        )
        .distinct()
        .order_by("-updated_at", "-id")
    )
    album_page = Paginator(album_stories, 10).get_page(album_page_number)
    for story in album_page.object_list:
        prepare_album_story(story, is_myself, viewer_person)

    return {
        "is_myself": is_myself,
        "interest_tags": [
            selection.tag
            for selection in selections
            if selection.kind == PersonProfileTag.Kind.INTEREST
        ],
        "interest_selections": [
            selection
            for selection in selections
            if selection.kind == PersonProfileTag.Kind.INTEREST
        ],
        "skill_tags": [
            selection.tag
            for selection in selections
            if selection.kind == PersonProfileTag.Kind.SKILL
        ],
        "skill_selections": [
            selection
            for selection in selections
            if selection.kind == PersonProfileTag.Kind.SKILL
        ],
        "custom_interest_tags": custom_interest_tags,
        "custom_skill_tags": custom_skill_tags,
        "interest_tag_tree": (
            _candidate_tree(ProfileTag.AppliesTo.INTEREST, interest_tag_ids)
            if is_myself else []
        ),
        "skill_tag_tree": (
            _candidate_tree(ProfileTag.AppliesTo.SKILL, skill_tag_ids)
            if is_myself else []
        ),
        "root_categories": [node for node in tree] if is_myself else [],
        "recent_activities": recent_activities,
        "activity_album": album_page,
        "activity_count": eligible_participations.count(),
        "course_count": CourseRecord.objects.valid().filter(person=person).count(),
        "organization_count": Position.objects.filter(
            person=person, show_post=True
        ).values("org_id").distinct().count(),
        "academic_count": (
            AcademicTagEntry.objects.activated().filter(person=person).count()
            + AcademicTextEntry.objects.activated().filter(person=person).count()
        ),
    }


def prepare_participation_story(participation: Participation, is_myself: bool):
    """Attach viewer-safe story attributes to a prefetched participation."""

    try:
        story = participation.story
    except ParticipationStory.DoesNotExist:
        participation.profile_story = None
        return participation
    story.display_description = (
        story.description
        if is_myself
        or story.description_status == ParticipationStory.ContentStatus.VISIBLE
        else ""
    )
    story.display_images = [
        image
        for image in story.images.all()
        if is_myself or image.status == ParticipationStoryImage.Status.VISIBLE
    ]
    participation.profile_story = story
    return participation


def prepare_album_story(
    story: ParticipationStory,
    is_myself: bool,
    viewer_person: NaturalPerson | None,
):
    """Attach viewer-safe content and interaction state to one album item."""

    story.display_description = (
        story.description
        if is_myself
        or story.description_status == ParticipationStory.ContentStatus.VISIBLE
        else ""
    )
    story.display_images = [
        image
        for image in story.images.all()
        if is_myself or image.status == ParticipationStoryImage.Status.VISIBLE
    ]
    story.display_comments = list(story.story_comments.all())
    story.like_count = len(story.likes.all())
    story.viewer_has_liked = bool(
        viewer_person
        and any(like.person_id == viewer_person.pk for like in story.likes.all())
    )
    story.can_interact = bool(viewer_person)
    story.participation.profile_story = story
    return story


def prepare_tag_story(
    selection: PersonProfileTag,
    viewer_person: NaturalPerson | None,
):
    """Attach interaction state to one prefetched interest or skill story."""

    selection.display_comments = list(selection.story_comments.all())
    selection.like_count = len(selection.likes.all())
    selection.viewer_has_liked = bool(
        viewer_person
        and any(like.person_id == viewer_person.pk for like in selection.likes.all())
    )
    selection.can_interact = bool(viewer_person)
    return selection


def activity_story_is_public(story: ParticipationStory):
    return bool(
        (
            story.description
            and story.description_status == ParticipationStory.ContentStatus.VISIBLE
        )
        or ParticipationStoryImage.objects.filter(
            story=story, status=ParticipationStoryImage.Status.VISIBLE
        ).exists()
    )


def tag_story_is_public(selection: PersonProfileTag):
    """Return whether an interest or skill selection is publicly visible."""

    _, active_category_ids = _active_category_tree()
    return bool(
        selection.kind in PersonProfileTag.Kind.values
        and selection.tag.status == ProfileTag.Status.VISIBLE
        and selection.tag.category_id in active_category_ids
    )


def build_activity_story_page(*, viewer_person, page_number=1, activity=None):
    """Build a newest-first page of public activity uploads."""

    eligible_statuses = [
        Participation.AttendStatus.APPLYSUCCESS,
        Participation.AttendStatus.ATTENDED,
    ]
    stories = ParticipationStory.objects.filter(
        participation__status__in=eligible_statuses,
    ).filter(
        Q(
            description_status=ParticipationStory.ContentStatus.VISIBLE,
            description__gt="",
        )
        | Q(images__status=ParticipationStoryImage.Status.VISIBLE)
    )
    if activity is not None:
        stories = stories.filter(participation__activity=activity)
    stories = (
        stories.select_related(
            "participation",
            "participation__person",
            "participation__person__person_id",
            "participation__activity",
            "participation__activity__organization_id",
        )
        .prefetch_related(
            Prefetch(
                "images",
                queryset=ParticipationStoryImage.objects.filter(
                    status=ParticipationStoryImage.Status.VISIBLE
                ),
                to_attr="visible_images",
            ),
            "likes",
            Prefetch(
                "story_comments",
                queryset=ParticipationStoryComment.objects.filter(
                    status=ParticipationStoryComment.Status.VISIBLE
                ).select_related("author", "author__person_id"),
                to_attr="visible_comments",
            ),
        )
        .distinct()
        .order_by("-updated_at", "-id")
    )
    page = Paginator(stories, 10).get_page(page_number)
    for story in page.object_list:
        story.display_description = (
            story.description
            if story.description_status == ParticipationStory.ContentStatus.VISIBLE
            else ""
        )
        story.display_images = story.visible_images
        story.display_comments = story.visible_comments
        story.like_count = len(story.likes.all())
        story.viewer_has_liked = bool(
            viewer_person
            and any(like.person_id == viewer_person.pk for like in story.likes.all())
        )
        story.can_interact = bool(viewer_person)
    return page


def build_skill_story_page(*, viewer_person, page_number=1):
    """Build a newest-first page of public interest and skill selections."""

    _, active_category_ids = _active_category_tree()
    selections = (
        PersonProfileTag.objects.filter(
            kind__in=PersonProfileTag.Kind.values,
            tag__status=ProfileTag.Status.VISIBLE,
            tag__category_id__in=active_category_ids,
        )
        .select_related("person", "person__person_id", "tag", "tag__category")
        .prefetch_related(
            Prefetch(
                "images",
                queryset=PersonProfileTagImage.objects.filter(
                    status=PersonProfileTagImage.Status.VISIBLE
                ),
                to_attr="visible_images",
            ),
            "likes",
            Prefetch(
                "story_comments",
                queryset=PersonProfileTagComment.objects.filter(
                    status=PersonProfileTagComment.Status.VISIBLE
                ).select_related("author", "author__person_id"),
                to_attr="visible_comments",
            ),
        )
        .distinct()
        .order_by("-updated_at", "-id")
    )
    page = Paginator(selections, 10).get_page(page_number)
    for selection in page.object_list:
        selection.display_description = (
            selection.description
            if selection.description_status == PersonProfileTag.ContentStatus.VISIBLE
            else ""
        )
        selection.display_images = selection.visible_images
        selection.display_comments = selection.visible_comments
        selection.like_count = len(selection.likes.all())
        selection.viewer_has_liked = bool(
            viewer_person
            and any(
                like.person_id == viewer_person.pk for like in selection.likes.all()
            )
        )
        selection.can_interact = bool(viewer_person)
    return page


def _descendant_category_ids(root_category: ProfileTagCategory):
    category_ids = [root_category.pk]
    pending_ids = [root_category.pk]
    visited_ids = {root_category.pk}
    while pending_ids:
        child_ids = list(
            ProfileTagCategory.objects.filter(
                parent_id__in=pending_ids, is_active=True
            ).values_list("id", flat=True)
        )
        child_ids = [child_id for child_id in child_ids if child_id not in visited_ids]
        visited_ids.update(child_ids)
        category_ids.extend(child_ids)
        pending_ids = child_ids
    return category_ids


def _resolve_custom_tag(person, root_category, display_name, kind):
    normalized_name = ProfileTag.normalize_name(display_name)
    applies_to = ProfileTag.AppliesTo(kind)
    matching_tags = ProfileTag.objects.filter(
        category_id__in=_descendant_category_ids(root_category),
        normalized_name=normalized_name,
    )
    compatible_tags = matching_tags.filter(
        applies_to__in=[applies_to, ProfileTag.AppliesTo.BOTH]
    )
    existing = (
        compatible_tags.filter(source=ProfileTag.Source.OFFICIAL).order_by("id").first()
        or compatible_tags.order_by("id").first()
    )
    if existing is not None:
        if existing.status != ProfileTag.Status.VISIBLE:
            raise ValidationError(f"标签“{display_name}”当前不可用，请更换内容。")
        return existing

    tag, _ = ProfileTag.objects.get_or_create(
        category=root_category,
        normalized_name=normalized_name,
        defaults={
            "name": display_name,
            "source": ProfileTag.Source.CUSTOM,
            "applies_to": applies_to,
            "status": ProfileTag.Status.VISIBLE,
            "created_by": person,
        },
    )
    if tag.status != ProfileTag.Status.VISIBLE:
        raise ValidationError(f"标签“{display_name}”当前不可用，请更换内容。")
    if tag.applies_to not in [applies_to, ProfileTag.AppliesTo.BOTH]:
        if tag.source != ProfileTag.Source.CUSTOM:
            raise ValidationError(f"标签“{display_name}”不属于当前候选类型。")
        tag.applies_to = ProfileTag.AppliesTo.BOTH
        tag.save(update_fields=["applies_to"])
    return tag


def replace_person_profile_tags(
    person: NaturalPerson,
    interest_tags,
    skill_tags,
    custom_tags,
):
    """Synchronize visible selections without replacing retained story content."""

    removed_image_names = []
    with transaction.atomic():
        locked_person = NaturalPerson.objects.select_for_update().get(pk=person.pk)
        selections = {
            PersonProfileTag.Kind.INTEREST: list(interest_tags),
            PersonProfileTag.Kind.SKILL: list(skill_tags),
        }
        for kind, values in custom_tags.items():
            selection_kind = PersonProfileTag.Kind(kind)
            for category_id, display_name in values:
                try:
                    root_category = ProfileTagCategory.objects.get(
                        pk=category_id,
                        parent__isnull=True,
                        is_active=True,
                    )
                except ProfileTagCategory.DoesNotExist as exc:
                    raise ValidationError(
                        "所选标签分类已不可用，请刷新页面重试。"
                    ) from exc
                selections[selection_kind].append(
                    _resolve_custom_tag(
                        locked_person, root_category, display_name, selection_kind
                    )
                )

        target_pairs = {
            (tag.pk, kind)
            for kind, tags in selections.items()
            for tag in {tag.pk: tag for tag in tags}.values()
        }
        current_selections = list(
            PersonProfileTag.objects.select_for_update().filter(
                person=locked_person,
                tag__status=ProfileTag.Status.VISIBLE,
            )
        )
        current_pairs = {
            (selection.tag_id, selection.kind): selection
            for selection in current_selections
        }
        removed_ids = [
            selection.pk
            for pair, selection in current_pairs.items()
            if pair not in target_pairs
        ]
        if removed_ids:
            removed_image_names = list(
                PersonProfileTagImage.objects.filter(selection_id__in=removed_ids)
                .exclude(image="")
                .values_list("image", flat=True)
            )
            PersonProfileTag.objects.filter(pk__in=removed_ids).delete()

        PersonProfileTag.objects.bulk_create(
            [
                PersonProfileTag(
                    person=locked_person,
                    tag_id=tag_id,
                    kind=kind,
                )
                for tag_id, kind in target_pairs - set(current_pairs)
            ],
            ignore_conflicts=True,
        )
        if removed_image_names:
            transaction.on_commit(
                lambda names=tuple(removed_image_names): _delete_stored_files(names)
            )


def _store_story_images(model_class, parent_field, parent, uploaded_images):
    """Store validated files before entering a database transaction."""

    field = model_class._meta.get_field("image")
    instance = model_class(**{parent_field: parent})
    stored_names = []
    try:
        for uploaded_image in uploaded_images:
            generated_name = field.generate_filename(instance, uploaded_image.name)
            stored_names.append(default_storage.save(generated_name, uploaded_image))
    except Exception:
        _delete_stored_files(stored_names)
        raise
    return stored_names


def _delete_stored_files(names):
    for name in names:
        if name:
            default_storage.delete(name)


def update_tag_story(
    *, person, selection, description, uploaded_images, delete_image_ids
):
    """Update one owned tag story while enforcing the six-image invariant."""

    if selection.person_id != person.pk:
        raise ValidationError("只能编辑自己的画像标签说明。")
    stored_names = _store_story_images(
        PersonProfileTagImage, "selection", selection, uploaded_images
    )
    deleted_names = []
    try:
        with transaction.atomic():
            locked_selection = (
                PersonProfileTag.objects.select_for_update()
                .select_related("tag")
                .get(pk=selection.pk, person=person)
            )
            if locked_selection.tag.status != ProfileTag.Status.VISIBLE:
                raise ValidationError("该标签当前不可编辑。")
            images = PersonProfileTagImage.objects.filter(selection=locked_selection)
            to_delete = images.filter(pk__in=delete_image_ids)
            deleted_count = to_delete.count()
            deleted_names = list(
                to_delete.exclude(image="").values_list("image", flat=True)
            )
            remaining_count = images.exclude(pk__in=delete_image_ids).count()
            if remaining_count + len(stored_names) > MAX_STORY_IMAGES:
                raise ValidationError(f"每个标签最多保留 {MAX_STORY_IMAGES} 张图片。")
            to_delete.delete()

            description_changed = locked_selection.description != description
            if description_changed:
                locked_selection.description = description
                locked_selection.description_status = (
                    PersonProfileTag.ContentStatus.VISIBLE
                )
            if description_changed or deleted_count or stored_names:
                update_fields = ["updated_at"]
                if description_changed:
                    update_fields.extend(["description", "description_status"])
                locked_selection.save(
                    update_fields=update_fields
                )
            next_order = remaining_count
            PersonProfileTagImage.objects.bulk_create(
                [
                    PersonProfileTagImage(
                        selection=locked_selection,
                        image=name,
                        sort_order=next_order + offset,
                    )
                    for offset, name in enumerate(stored_names)
                ]
            )
            if deleted_names:
                transaction.on_commit(
                    lambda names=tuple(deleted_names): _delete_stored_files(names)
                )
    except Exception:
        _delete_stored_files(stored_names)
        raise


def update_activity_story(
    *, person, participation, description, uploaded_images, delete_image_ids
):
    """Update one owned eligible participation story."""

    if participation.person_id != person.pk:
        raise ValidationError("只能编辑自己的活动记录。")
    stored_names = _store_story_images(
        ParticipationStoryImage, "story", None, uploaded_images
    )
    deleted_names = []
    eligible_statuses = {
        Participation.AttendStatus.APPLYSUCCESS,
        Participation.AttendStatus.ATTENDED,
    }
    try:
        with transaction.atomic():
            locked_participation = Participation.objects.select_for_update().get(
                pk=participation.pk, person=person
            )
            if locked_participation.status not in eligible_statuses:
                raise ValidationError("只有已报名或已参与的活动可以添加个人记录。")
            story, _ = ParticipationStory.objects.get_or_create(
                participation=locked_participation
            )
            images = ParticipationStoryImage.objects.filter(story=story)
            to_delete = images.filter(pk__in=delete_image_ids)
            deleted_count = to_delete.count()
            deleted_names = list(
                to_delete.exclude(image="").values_list("image", flat=True)
            )
            remaining_count = images.exclude(pk__in=delete_image_ids).count()
            if remaining_count + len(stored_names) > MAX_STORY_IMAGES:
                raise ValidationError(f"每条活动记录最多保留 {MAX_STORY_IMAGES} 张图片。")
            to_delete.delete()

            description_changed = story.description != description
            if description_changed:
                story.description = description
                story.description_status = ParticipationStory.ContentStatus.VISIBLE
            if description_changed or deleted_count or stored_names:
                update_fields = ["updated_at"]
                if description_changed:
                    update_fields.extend(["description", "description_status"])
                story.save(
                    update_fields=update_fields
                )
            next_order = remaining_count
            ParticipationStoryImage.objects.bulk_create(
                [
                    ParticipationStoryImage(
                        story=story,
                        image=name,
                        sort_order=next_order + offset,
                    )
                    for offset, name in enumerate(stored_names)
                ]
            )
            if deleted_names:
                transaction.on_commit(
                    lambda names=tuple(deleted_names): _delete_stored_files(names)
                )
    except Exception:
        _delete_stored_files(stored_names)
        raise


def toggle_activity_story_like(*, person, story):
    """Atomically toggle a visitor's like on a public activity story."""

    eligible_statuses = {
        Participation.AttendStatus.APPLYSUCCESS,
        Participation.AttendStatus.ATTENDED,
    }
    with transaction.atomic():
        locked_story = (
            ParticipationStory.objects.select_for_update()
            .select_related("participation")
            .get(pk=story.pk)
        )
        if locked_story.participation.status not in eligible_statuses:
            raise ValidationError("该活动记录当前不可互动。")
        if not activity_story_is_public(locked_story):
            raise ValidationError("该活动记录当前不可见。")
        existing_like = ParticipationStoryLike.objects.filter(
            story=locked_story, person=person
        ).first()
        if existing_like:
            existing_like.delete()
            return False
        ParticipationStoryLike.objects.create(story=locked_story, person=person)
        return True


def add_activity_story_comment(*, person, story, content):
    """Create an immediately public visitor comment after rechecking visibility."""

    eligible_statuses = {
        Participation.AttendStatus.APPLYSUCCESS,
        Participation.AttendStatus.ATTENDED,
    }
    with transaction.atomic():
        locked_story = (
            ParticipationStory.objects.select_for_update()
            .select_related("participation")
            .get(pk=story.pk)
        )
        if locked_story.participation.status not in eligible_statuses:
            raise ValidationError("该活动记录当前不可互动。")
        if not activity_story_is_public(locked_story):
            raise ValidationError("该活动记录当前不可见。")
        return ParticipationStoryComment.objects.create(
            story=locked_story,
            author=person,
            content=content,
        )


def toggle_tag_story_like(*, person, selection):
    """Atomically toggle a person's like on a public interest or skill story."""

    with transaction.atomic():
        locked_selection = (
            PersonProfileTag.objects.select_for_update()
            .select_related("tag", "tag__category")
            .get(pk=selection.pk)
        )
        if not tag_story_is_public(locked_selection):
            raise ValidationError("该兴趣或技能记录当前不可见。")
        existing_like = PersonProfileTagLike.objects.filter(
            selection=locked_selection, person=person
        ).first()
        if existing_like:
            existing_like.delete()
            return False
        PersonProfileTagLike.objects.create(
            selection=locked_selection, person=person
        )
        return True


def add_tag_story_comment(*, person, selection, content):
    """Create a person's public comment on an interest or skill story."""

    with transaction.atomic():
        locked_selection = (
            PersonProfileTag.objects.select_for_update()
            .select_related("tag", "tag__category")
            .get(pk=selection.pk)
        )
        if not tag_story_is_public(locked_selection):
            raise ValidationError("该兴趣或技能记录当前不可见。")
        return PersonProfileTagComment.objects.create(
            selection=locked_selection,
            author=person,
            content=content,
        )


def delete_activity_story(*, person, story):
    """Delete one owned story and reclaim its uploaded files after commit."""

    with transaction.atomic():
        locked_story = (
            ParticipationStory.objects.select_for_update()
            .select_related("participation")
            .get(pk=story.pk, participation__person=person)
        )
        image_names = list(
            locked_story.images.exclude(image="").values_list("image", flat=True)
        )
        locked_story.delete()
        if image_names:
            transaction.on_commit(
                lambda names=tuple(image_names): _delete_stored_files(names)
            )
