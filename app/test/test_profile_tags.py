from datetime import datetime, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from PIL import Image

from app.models import (
    Activity,
    ActivityPhoto,
    NaturalPerson,
    Organization,
    OrganizationType,
    Participation,
    ParticipationStory,
    ParticipationStoryComment,
    ParticipationStoryImage,
    ParticipationStoryLike,
    PersonProfileTag,
    PersonProfileTagComment,
    PersonProfileTagImage,
    PersonProfileTagLike,
    ProfileTag,
    ProfileTagCategory,
    User,
)
from app.profile_forms import ProfileTagUpdateForm
from app.profile_utils import build_profile_context, replace_person_profile_tags


class ProfileTagFeatureTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "profile-owner",
            "Profile Owner",
            User.Type.STUDENT,
            password="pw",
            is_newuser=False,
        )
        cls.person = NaturalPerson.objects.create(cls.user, name="画像同学")
        cls.visitor_user = User.objects.create_user(
            "profile-visitor",
            "Profile Visitor",
            User.Type.STUDENT,
            password="pw",
            is_newuser=False,
        )
        cls.visitor = NaturalPerson.objects.create(cls.visitor_user, name="访客同学")

        cls.root = ProfileTagCategory.objects.create(
            name="测试艺术", slug="test-art", sort_order=100
        )
        cls.child = ProfileTagCategory.objects.create(
            name="测试视觉", slug="test-visual", parent=cls.root
        )
        cls.official_tag = ProfileTag.objects.create(
            category=cls.child,
            name="摄影",
            source=ProfileTag.Source.OFFICIAL,
            applies_to=ProfileTag.AppliesTo.BOTH,
        )
        cls.skill_only_tag = ProfileTag.objects.create(
            category=cls.child,
            name="图像处理",
            source=ProfileTag.Source.OFFICIAL,
            applies_to=ProfileTag.AppliesTo.SKILL,
        )

        cls.teacher_user = User.objects.create_user(
            "profile-teacher",
            "Profile Teacher",
            User.Type.TEACHER,
            password="pw",
            is_newuser=False,
        )
        cls.teacher = NaturalPerson.objects.create(
            cls.teacher_user,
            name="画像教师",
            identity=NaturalPerson.Identity.TEACHER,
        )
        cls.otype = OrganizationType.objects.create(
            otype_id=9901,
            otype_name="画像测试组织类型",
            incharge=cls.teacher,
            job_name_list=["负责人", "副负责人", "成员", "干事"],
        )
        cls.org_user = User.objects.create_user(
            "profile-org",
            "Profile Org",
            User.Type.ORG,
            password="pw",
            is_newuser=False,
        )
        cls.org = Organization.objects.create(
            organization_id=cls.org_user,
            oname="画像测试组织",
            otype=cls.otype,
        )

    def _create_activity_participation(self, title, participation_status):
        start = datetime.now() + timedelta(days=1)
        activity = Activity.objects.create(
            title=title,
            organization_id=self.org,
            start=start,
            end=start + timedelta(hours=2),
            apply_end=start - timedelta(hours=1),
            examine_teacher=self.teacher,
            valid=True,
        )
        return Participation.objects.create(
            activity=activity,
            person=self.person,
            status=participation_status,
        )

    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()

    def tearDown(self):
        self.media_override.disable()
        self.media_directory.cleanup()
        super().tearDown()

    @staticmethod
    def _image_file(name="story.png", extra_bytes=0):
        stream = BytesIO()
        Image.new("RGB", (8, 8), color=(90, 120, 180)).save(stream, format="PNG")
        content = stream.getvalue() + b"x" * extra_bytes
        return SimpleUploadedFile(name, content, content_type="image/png")

    def test_normalized_name_is_unique_in_one_category(self):
        ProfileTag.objects.create(category=self.root, name="  胶片   摄影  ")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfileTag.objects.create(category=self.root, name="胶片 摄影")

    def test_profile_context_counts_registered_and_attended_only(self):
        self._create_activity_participation(
            "已报名活动", Participation.AttendStatus.APPLYSUCCESS
        )
        self._create_activity_participation(
            "已参与活动", Participation.AttendStatus.ATTENDED
        )
        self._create_activity_participation(
            "未签到活动", Participation.AttendStatus.UNATTENDED
        )
        self._create_activity_participation(
            "已放弃活动", Participation.AttendStatus.CANCELED
        )

        context = build_profile_context(self.person, is_myself=True)

        self.assertEqual(context["activity_count"], 2)
        self.assertEqual(
            {item.status for item in context["recent_activities"]},
            {
                Participation.AttendStatus.APPLYSUCCESS,
                Participation.AttendStatus.ATTENDED,
            },
        )

    def test_owner_can_select_official_and_create_immediately_visible_tag(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/profile/tags/update/",
            {
                "interest_tags": [self.official_tag.pk],
                f"custom_skill_{self.root.pk}": "胶片摄影",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            PersonProfileTag.objects.filter(person=self.person).count(), 2
        )
        custom_tag = ProfileTag.objects.get(
            category=self.root,
            normalized_name=ProfileTag.normalize_name("胶片摄影"),
        )
        self.assertEqual(custom_tag.source, ProfileTag.Source.CUSTOM)
        self.assertEqual(custom_tag.applies_to, ProfileTag.AppliesTo.SKILL)
        self.assertEqual(custom_tag.status, ProfileTag.Status.VISIBLE)
        visitor_context = build_profile_context(self.person, is_myself=False)
        self.assertIn(custom_tag, visitor_context["skill_tags"])

    def test_admin_hidden_tag_disappears_from_every_profile(self):
        PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        self.official_tag.status = ProfileTag.Status.HIDDEN
        self.official_tag.save(update_fields=["status"])

        context = build_profile_context(self.person, is_myself=False)

        self.assertEqual(context["interest_tags"], [])
        self.assertTrue(admin.site.is_registered(ProfileTag))
        self.assertTrue(admin.site.is_registered(PersonProfileTag))

    def test_interest_and_skill_use_distinct_candidate_subpools(self):
        form = ProfileTagUpdateForm(
            {
                "interest_tags": [self.skill_only_tag.pk],
                "skill_tags": [self.skill_only_tag.pk],
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("interest_tags", form.errors)
        self.assertNotIn("skill_tags", form.errors)

        context = build_profile_context(self.person, is_myself=True)

        def tag_names(nodes):
            return {
                tag["name"]
                for node in nodes
                for tag in node["tags"]
            } | {
                name
                for node in nodes
                for name in tag_names(node["children"])
            }

        self.assertNotIn("图像处理", tag_names(context["interest_tag_tree"]))
        self.assertIn("图像处理", tag_names(context["skill_tag_tree"]))
        self.assertIn("摄影", tag_names(context["interest_tag_tree"]))
        self.assertIn("摄影", tag_names(context["skill_tag_tree"]))

    def test_update_endpoint_rejects_organization_account(self):
        self.client.force_login(self.org_user)

        response = self.client.post("/profile/tags/update/", {})

        self.assertEqual(response.status_code, 403)

    def test_update_endpoint_enforces_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post("/profile/tags/update/", {})

        self.assertEqual(response.status_code, 403)

    def test_profile_page_issues_cookie_for_valid_csrf_submission(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        profile_response = csrf_client.get(self.person.get_absolute_url())

        self.assertEqual(profile_response.status_code, 200)
        self.assertIn("csrftoken", profile_response.cookies)
        csrf_token = profile_response.cookies["csrftoken"].value

        update_response = csrf_client.post(
            "/profile/tags/update/",
            {"interest_tags": [self.official_tag.pk]},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(update_response.status_code, 302)
        self.assertTrue(
            PersonProfileTag.objects.filter(
                person=self.person,
                tag=self.official_tag,
                kind=PersonProfileTag.Kind.INTEREST,
            ).exists()
        )

    def test_retained_tag_keeps_description_and_images_during_list_update(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
            description="我用摄影记录校园。",
        )
        image = PersonProfileTagImage.objects.create(
            selection=selection, image=self._image_file()
        )

        replace_person_profile_tags(
            person=self.person,
            interest_tags=[self.official_tag],
            skill_tags=[],
            custom_tags={"interest": [], "skill": []},
        )

        selection.refresh_from_db()
        self.assertEqual(selection.description, "我用摄影记录校园。")
        self.assertTrue(PersonProfileTagImage.objects.filter(pk=image.pk).exists())

    def test_unselected_tag_cascades_its_story_images(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        image = PersonProfileTagImage.objects.create(
            selection=selection, image=self._image_file()
        )

        with self.captureOnCommitCallbacks(execute=True):
            replace_person_profile_tags(
                person=self.person,
                interest_tags=[],
                skill_tags=[],
                custom_tags={"interest": [], "skill": []},
            )

        self.assertFalse(PersonProfileTag.objects.filter(pk=selection.pk).exists())
        self.assertFalse(PersonProfileTagImage.objects.filter(pk=image.pk).exists())

    def test_tag_story_owner_can_upload_and_visitor_cannot_edit(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"/profile/tags/{selection.pk}/story/",
            {"description": "从胶片到数码", "images": [self._image_file()]},
        )

        self.assertEqual(response.status_code, 302)
        selection.refresh_from_db()
        self.assertEqual(selection.description, "从胶片到数码")
        self.assertEqual(selection.images.count(), 1)

        self.client.force_login(self.visitor_user)
        response = self.client.post(
            f"/profile/tags/{selection.pk}/story/",
            {"description": "越权修改"},
        )
        self.assertEqual(response.status_code, 404)

    def test_activity_story_requires_owned_eligible_participation(self):
        registered = self._create_activity_participation(
            "已报名也可记录", Participation.AttendStatus.APPLYSUCCESS
        )
        eligible = self._create_activity_participation(
            "可以记录", Participation.AttendStatus.ATTENDED
        )
        ineligible = self._create_activity_participation(
            "不可记录", Participation.AttendStatus.UNATTENDED
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"/profile/activities/{registered.pk}/story/",
            {"description": "报名后的期待"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ParticipationStory.objects.filter(participation=registered).exists()
        )

        response = self.client.post(
            f"/profile/activities/{eligible.pk}/story/",
            {"description": "一次难忘的活动", "images": [self._image_file()]},
        )
        self.assertEqual(response.status_code, 302)
        story = ParticipationStory.objects.get(participation=eligible)
        self.assertEqual(story.description, "一次难忘的活动")
        self.assertEqual(story.images.count(), 1)

        response = self.client.post(
            f"/profile/activities/{ineligible.pk}/story/",
            {"description": "不应保存"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("story=invalid", response.url)
        self.assertFalse(
            ParticipationStory.objects.filter(participation=ineligible).exists()
        )

        self.client.force_login(self.visitor_user)
        response = self.client.post(
            f"/profile/activities/{eligible.pk}/story/",
            {"description": "越权修改"},
        )
        self.assertEqual(response.status_code, 404)

    def test_activity_story_moderation_filters_text_and_images_for_visitors(self):
        participation = self._create_activity_participation(
            "活动故事审核", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation,
            description="已隐藏的活动心得",
            description_status=ParticipationStory.ContentStatus.HIDDEN,
        )
        hidden_image = ParticipationStoryImage.objects.create(
            story=story,
            image=self._image_file("activity-hidden.png"),
            status=ParticipationStoryImage.Status.HIDDEN,
        )
        visible_image = ParticipationStoryImage.objects.create(
            story=story, image=self._image_file("activity-visible.png")
        )

        visitor_context = build_profile_context(self.person, is_myself=False)
        visitor_story = next(
            item.profile_story
            for item in visitor_context["recent_activities"]
            if item.pk == participation.pk
        )
        self.assertEqual(visitor_story.display_description, "")
        self.assertEqual(
            [image.pk for image in visitor_story.display_images],
            [visible_image.pk],
        )
        self.assertTrue(
            ParticipationStoryImage.objects.filter(pk=hidden_image.pk).exists()
        )
        self.assertTrue(admin.site.is_registered(ParticipationStory))
        self.assertTrue(admin.site.is_registered(ParticipationStoryImage))
        self.assertTrue(admin.site.is_registered(PersonProfileTagImage))

    def test_admin_can_hide_text_or_one_image_without_hiding_parent(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
            description="公开说明",
            description_status=PersonProfileTag.ContentStatus.HIDDEN,
        )
        hidden_image = PersonProfileTagImage.objects.create(
            selection=selection,
            image=self._image_file("hidden.png"),
            status=PersonProfileTagImage.Status.HIDDEN,
        )
        visible_image = PersonProfileTagImage.objects.create(
            selection=selection,
            image=self._image_file("visible.png"),
        )

        visitor_selection = build_profile_context(
            self.person, is_myself=False
        )["interest_selections"][0]
        self.assertEqual(visitor_selection.display_description, "")
        self.assertEqual(
            [image.pk for image in visitor_selection.display_images],
            [visible_image.pk],
        )
        self.assertEqual(visitor_selection.tag, self.official_tag)
        self.assertTrue(PersonProfileTagImage.objects.filter(pk=hidden_image.pk).exists())

    def test_upload_rejects_non_image_oversize_and_more_than_six(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        self.client.force_login(self.user)

        non_image = SimpleUploadedFile(
            "not-image.txt", b"plain text", content_type="text/plain"
        )
        response = self.client.post(
            f"/profile/tags/{selection.pk}/story/", {"images": [non_image]}
        )
        self.assertIn("story=invalid", response.url)
        self.assertEqual(selection.images.count(), 0)

        oversized = self._image_file(
            "large.png", extra_bytes=5 * 1024 * 1024
        )
        response = self.client.post(
            f"/profile/tags/{selection.pk}/story/", {"images": [oversized]}
        )
        self.assertIn("story=invalid", response.url)
        self.assertEqual(selection.images.count(), 0)

        response = self.client.post(
            f"/profile/tags/{selection.pk}/story/",
            {"images": [self._image_file(f"image-{index}.png") for index in range(7)]},
        )
        self.assertIn("story=invalid", response.url)
        self.assertEqual(selection.images.count(), 0)

    def test_owner_can_delete_one_existing_image(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        first = PersonProfileTagImage.objects.create(
            selection=selection, image=self._image_file("first.png")
        )
        second = PersonProfileTagImage.objects.create(
            selection=selection, image=self._image_file("second.png")
        )
        self.client.force_login(self.user)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/profile/tags/{selection.pk}/story/",
                {"delete_images": [str(first.pk)]},
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(PersonProfileTagImage.objects.filter(pk=first.pk).exists())
        self.assertTrue(PersonProfileTagImage.objects.filter(pk=second.pk).exists())

    def test_tag_story_image_only_upload_and_delete_update_timestamp(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        old_time = datetime.now() - timedelta(days=2)
        PersonProfileTag.objects.filter(pk=selection.pk).update(updated_at=old_time)
        self.client.force_login(self.user)

        upload_response = self.client.post(
            f"/profile/tags/{selection.pk}/story/",
            {"images": [self._image_file("timestamp-upload.png")]},
        )

        self.assertEqual(upload_response.status_code, 302)
        selection.refresh_from_db()
        self.assertGreater(selection.updated_at, old_time)
        uploaded_image = selection.images.get()

        delete_old_time = datetime.now() - timedelta(days=1)
        PersonProfileTag.objects.filter(pk=selection.pk).update(
            updated_at=delete_old_time
        )
        with self.captureOnCommitCallbacks(execute=True):
            delete_response = self.client.post(
                f"/profile/tags/{selection.pk}/story/",
                {"delete_images": [str(uploaded_image.pk)]},
            )

        self.assertEqual(delete_response.status_code, 302)
        selection.refresh_from_db()
        self.assertGreater(selection.updated_at, delete_old_time)
        self.assertFalse(
            PersonProfileTagImage.objects.filter(pk=uploaded_image.pk).exists()
        )

    def test_story_endpoints_are_post_only_and_csrf_protected(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(f"/profile/tags/{selection.pk}/story/").status_code,
            405,
        )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(
            csrf_client.post(
                f"/profile/tags/{selection.pk}/story/", {"description": "x"}
            ).status_code,
            403,
        )

    def test_profile_page_renders_public_tag_and_activity_stories(self):
        PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
            description="页面上的摄影故事",
        )
        participation = self._create_activity_participation(
            "页面活动故事", Participation.AttendStatus.ATTENDED
        )
        ParticipationStory.objects.create(
            participation=participation, description="页面上的活动心得"
        )

        self.client.force_login(self.user)
        owner_response = self.client.get(self.person.get_absolute_url())
        self.assertEqual(owner_response.status_code, 200)
        self.assertContains(owner_response, "页面上的摄影故事")
        self.assertContains(owner_response, "页面上的活动心得")

        self.client.force_login(self.visitor_user)
        visitor_response = self.client.get(self.person.get_absolute_url())
        self.assertEqual(visitor_response.status_code, 200)
        self.assertContains(visitor_response, "页面上的摄影故事")
        self.assertContains(visitor_response, "页面上的活动心得")

    def test_public_album_is_inline_newest_first_and_filters_hidden_story(self):
        older_participation = self._create_activity_participation(
            "较早的相册活动", Participation.AttendStatus.ATTENDED
        )
        newer_participation = self._create_activity_participation(
            "较新的相册活动", Participation.AttendStatus.APPLYSUCCESS
        )
        hidden_participation = self._create_activity_participation(
            "完全隐藏的相册活动", Participation.AttendStatus.ATTENDED
        )
        older_story = ParticipationStory.objects.create(
            participation=older_participation, description="较早的公开动态"
        )
        newer_story = ParticipationStory.objects.create(
            participation=newer_participation, description="较新的公开动态"
        )
        ParticipationStory.objects.create(
            participation=hidden_participation,
            description="不应对访客出现",
            description_status=ParticipationStory.ContentStatus.HIDDEN,
        )
        now = datetime.now()
        ParticipationStory.objects.filter(pk=older_story.pk).update(
            updated_at=now - timedelta(days=1)
        )
        ParticipationStory.objects.filter(pk=newer_story.pk).update(updated_at=now)

        context = build_profile_context(
            self.person,
            is_myself=False,
            viewer_person=self.visitor,
        )

        album_ids = [story.pk for story in context["activity_album"]]
        self.assertEqual(album_ids[:2], [newer_story.pk, older_story.pk])
        self.assertNotIn(hidden_participation.story.pk, album_ids)

        self.client.force_login(self.visitor_user)
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, "活动相册")
        self.assertContains(response, "较新的公开动态")
        self.assertContains(response, "较早的公开动态")
        self.assertNotContains(response, "不应对访客出现")

    def test_visitor_and_owner_can_like_and_comment_activity_story(self):
        participation = self._create_activity_participation(
            "允许互动的活动", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation, description="欢迎互动"
        )
        self.client.force_login(self.visitor_user)

        response = self.client.post(
            f"/profile/activity-stories/{story.pk}/like/"
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ParticipationStoryLike.objects.filter(
                story=story, person=self.visitor
            ).exists()
        )

        self.client.post(f"/profile/activity-stories/{story.pk}/like/")
        self.assertFalse(
            ParticipationStoryLike.objects.filter(
                story=story, person=self.visitor
            ).exists()
        )

        response = self.client.post(
            f"/profile/activity-stories/{story.pk}/comments/",
            {"content": "这张照片很有感染力！"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ParticipationStoryComment.objects.filter(
                story=story,
                author=self.visitor,
                content="这张照片很有感染力！",
            ).exists()
        )

        self.client.force_login(self.user)
        self.client.post(f"/profile/activity-stories/{story.pk}/like/")
        self.client.post(
            f"/profile/activity-stories/{story.pk}/comments/",
            {"content": "主人补充评论"},
        )
        self.assertTrue(
            ParticipationStoryLike.objects.filter(story=story, person=self.person).exists()
        )
        self.assertTrue(
            ParticipationStoryComment.objects.filter(
                story=story, author=self.person, content="主人补充评论"
            ).exists()
        )

        profile_response = self.client.get(self.person.get_absolute_url())
        self.assertContains(profile_response, "主人补充评论")
        self.assertContains(profile_response, "取消点赞")

    def test_hidden_comment_is_not_rendered_in_album(self):
        participation = self._create_activity_participation(
            "评论审核活动", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation, description="公开活动内容"
        )
        ParticipationStoryComment.objects.create(
            story=story, author=self.visitor, content="公开评论"
        )
        ParticipationStoryComment.objects.create(
            story=story,
            author=self.visitor,
            content="已隐藏评论",
            status=ParticipationStoryComment.Status.HIDDEN,
        )

        context = build_profile_context(
            self.person,
            is_myself=False,
            viewer_person=self.visitor,
        )
        album_story = next(item for item in context["activity_album"] if item.pk == story.pk)
        self.assertEqual(
            [comment.content for comment in album_story.display_comments],
            ["公开评论"],
        )
        self.assertTrue(admin.site.is_registered(ParticipationStoryLike))
        self.assertTrue(admin.site.is_registered(ParticipationStoryComment))

    def test_owner_can_delete_story_with_images_comments_and_likes(self):
        participation = self._create_activity_participation(
            "待删除活动记录", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation, description="准备删除"
        )
        image = ParticipationStoryImage.objects.create(
            story=story, image=self._image_file("delete-story.png")
        )
        ParticipationStoryLike.objects.create(story=story, person=self.visitor)
        ParticipationStoryComment.objects.create(
            story=story, author=self.visitor, content="即将级联删除"
        )
        self.client.force_login(self.visitor_user)
        forbidden_response = self.client.post(
            f"/profile/activity-stories/{story.pk}/delete/"
        )
        self.assertEqual(forbidden_response.status_code, 404)
        self.assertTrue(ParticipationStory.objects.filter(pk=story.pk).exists())

        self.client.force_login(self.user)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/profile/activity-stories/{story.pk}/delete/"
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ParticipationStory.objects.filter(pk=story.pk).exists())
        self.assertFalse(ParticipationStoryImage.objects.filter(pk=image.pk).exists())
        self.assertFalse(ParticipationStoryLike.objects.filter(story_id=story.pk).exists())
        self.assertFalse(
            ParticipationStoryComment.objects.filter(story_id=story.pk).exists()
        )

    def test_activity_story_image_only_edit_updates_album_order_timestamp(self):
        participation = self._create_activity_participation(
            "图片更新时间活动", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation, description="原动态"
        )
        old_time = datetime.now() - timedelta(days=2)
        ParticipationStory.objects.filter(pk=story.pk).update(updated_at=old_time)
        self.client.force_login(self.user)

        response = self.client.post(
            f"/profile/activities/{participation.pk}/story/",
            {"description": "原动态", "images": [self._image_file("new-photo.png")]},
        )

        self.assertEqual(response.status_code, 302)
        story.refresh_from_db()
        self.assertGreater(story.updated_at, old_time)

    def test_album_interaction_endpoints_are_post_only_and_csrf_protected(self):
        participation = self._create_activity_participation(
            "互动安全活动", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation, description="公开动态"
        )
        self.client.force_login(self.visitor_user)
        self.assertEqual(
            self.client.get(
                f"/profile/activity-stories/{story.pk}/like/"
            ).status_code,
            405,
        )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.visitor_user)
        self.assertEqual(
            csrf_client.post(
                f"/profile/activity-stories/{story.pk}/comments/",
                {"content": "缺少 CSRF"},
            ).status_code,
            403,
        )

    def test_community_boards_show_public_activity_and_skill_uploads(self):
        participation = self._create_activity_participation(
            "社区活动", Participation.AttendStatus.ATTENDED
        )
        ParticipationStory.objects.create(
            participation=participation, description="活动社区公开内容"
        )
        hidden_participation = self._create_activity_participation(
            "隐藏社区活动", Participation.AttendStatus.ATTENDED
        )
        ParticipationStory.objects.create(
            participation=hidden_participation,
            description="活动社区隐藏内容",
            description_status=ParticipationStory.ContentStatus.HIDDEN,
        )
        PersonProfileTag.objects.create(
            person=self.person,
            tag=self.skill_only_tag,
            kind=PersonProfileTag.Kind.SKILL,
        )
        PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )

        self.client.force_login(self.visitor_user)
        activity_response = self.client.get("/community/activities/")
        skill_response = self.client.get("/community/skills/")

        self.assertEqual(activity_response.status_code, 200)
        self.assertContains(activity_response, "活动社区公开内容")
        self.assertNotContains(activity_response, "活动社区隐藏内容")
        self.assertEqual(skill_response.status_code, 200)
        self.assertContains(skill_response, "近期兴趣与技能动态")
        self.assertContains(skill_response, "技能 · 图像处理")
        self.assertContains(skill_response, "兴趣 · 摄影")
        self.assertContains(skill_response, "还没有添加图文说明")

    def test_community_hides_moderated_tag_text_but_keeps_public_image(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.skill_only_tag,
            kind=PersonProfileTag.Kind.SKILL,
            description="技能社区不应泄露的隐藏文字",
            description_status=PersonProfileTag.ContentStatus.HIDDEN,
        )
        visible_image = PersonProfileTagImage.objects.create(
            selection=selection,
            image=self._image_file("public-skill-image.png"),
        )
        self.client.force_login(self.visitor_user)

        response = self.client.get("/community/skills/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "技能社区不应泄露的隐藏文字")
        self.assertContains(response, visible_image.image.url)

    def test_activity_feeds_hide_moderated_text_but_keep_public_image(self):
        participation = self._create_activity_participation(
            "隐藏文字公开图片活动", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation,
            description="活动社区和详情不应泄露的隐藏文字",
            description_status=ParticipationStory.ContentStatus.HIDDEN,
        )
        visible_image = ParticipationStoryImage.objects.create(
            story=story,
            image=self._image_file("public-activity-image.png"),
        )
        participation.activity.status = Activity.Status.END
        participation.activity.save(update_fields=["status"])
        ActivityPhoto.objects.create(
            activity=participation.activity,
            type=ActivityPhoto.PhotoType.ANNOUNCE,
            image="assets/img/announcepics/1.JPG",
        )
        self.client.force_login(self.visitor_user)

        community_response = self.client.get("/community/activities/")
        detail_response = self.client.get(
            f"/viewActivity/{participation.activity_id}"
        )

        for response in (community_response, detail_response):
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(
                response, "活动社区和详情不应泄露的隐藏文字"
            )
            self.assertContains(response, visible_image.image.url)

    def test_inactive_parent_category_hides_child_tag_from_community(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.skill_only_tag,
            kind=PersonProfileTag.Kind.SKILL,
            description="停用父分类后不可见的技能故事",
        )
        self.root.is_active = False
        self.root.save(update_fields=["is_active"])
        self.client.force_login(self.visitor_user)

        response = self.client.get("/community/skills/")
        like_response = self.client.post(
            f"/profile/skill-stories/{selection.pk}/like/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "停用父分类后不可见的技能故事")
        self.assertEqual(like_response.status_code, 403)

    def test_interest_story_uses_shared_board_like_and_comment_data(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.official_tag,
            kind=PersonProfileTag.Kind.INTEREST,
        )
        self.client.force_login(self.visitor_user)

        like_response = self.client.post(
            f"/profile/tag-stories/{selection.pk}/like/",
            {"next": "/community/skills/"},
        )
        comment_response = self.client.post(
            f"/profile/tag-stories/{selection.pk}/comments/",
            {"content": "我也喜欢摄影！", "next": "/community/skills/"},
        )

        self.assertEqual(like_response.status_code, 302)
        self.assertEqual(comment_response.status_code, 302)
        self.assertTrue(
            PersonProfileTagLike.objects.filter(
                selection=selection, person=self.visitor
            ).exists()
        )
        self.assertTrue(
            PersonProfileTagComment.objects.filter(
                selection=selection,
                author=self.visitor,
                content="我也喜欢摄影！",
            ).exists()
        )
        board_response = self.client.get("/community/skills/")
        profile_response = self.client.get(self.person.get_absolute_url())
        self.assertContains(board_response, "我也喜欢摄影！")
        self.assertContains(profile_response, "我也喜欢摄影！")

        self.client.force_login(self.user)
        owner_board_response = self.client.get("/community/skills/")
        self.assertContains(owner_board_response, "点赞")
        self.client.post(f"/profile/tag-stories/{selection.pk}/like/")
        self.client.post(
            f"/profile/tag-stories/{selection.pk}/comments/",
            {"content": "主人补充兴趣说明"},
        )
        self.assertTrue(
            PersonProfileTagLike.objects.filter(
                selection=selection, person=self.person
            ).exists()
        )
        self.assertTrue(
            PersonProfileTagComment.objects.filter(
                selection=selection,
                author=self.person,
                content="主人补充兴趣说明",
            ).exists()
        )

    def test_skill_story_interactions_are_shared_with_profile_and_board(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.skill_only_tag,
            kind=PersonProfileTag.Kind.SKILL,
        )
        self.client.force_login(self.visitor_user)

        like_response = self.client.post(
            f"/profile/skill-stories/{selection.pk}/like/",
            {"next": "/community/skills/"},
        )
        comment_response = self.client.post(
            f"/profile/skill-stories/{selection.pk}/comments/",
            {"content": "这个技能分享很实用！", "next": "/community/skills/"},
        )

        self.assertRedirects(
            like_response, "/community/skills/", fetch_redirect_response=False
        )
        self.assertRedirects(
            comment_response, "/community/skills/", fetch_redirect_response=False
        )
        self.assertTrue(
            PersonProfileTagLike.objects.filter(
                selection=selection, person=self.visitor
            ).exists()
        )
        self.assertTrue(
            PersonProfileTagComment.objects.filter(
                selection=selection,
                author=self.visitor,
                content="这个技能分享很实用！",
            ).exists()
        )

        board_response = self.client.get("/community/skills/")
        profile_response = self.client.get(self.person.get_absolute_url())
        self.assertContains(board_response, "这个技能分享很实用！")
        self.assertContains(profile_response, "这个技能分享很实用！")
        self.assertContains(profile_response, "取消点赞")

        self.client.force_login(self.user)
        self.client.post(f"/profile/skill-stories/{selection.pk}/like/")
        self.client.post(
            f"/profile/skill-stories/{selection.pk}/comments/",
            {"content": "主人补充技能说明"},
        )
        self.assertTrue(
            PersonProfileTagLike.objects.filter(
                selection=selection, person=self.person
            ).exists()
        )
        self.assertTrue(
            PersonProfileTagComment.objects.filter(
                selection=selection,
                author=self.person,
                content="主人补充技能说明",
            ).exists()
        )

    def test_community_page_issues_cookie_for_csrf_protected_comment(self):
        participation = self._create_activity_participation(
            "社区 CSRF 活动", Participation.AttendStatus.ATTENDED
        )
        story = ParticipationStory.objects.create(
            participation=participation, description="社区 CSRF 动态"
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.visitor_user)

        page_response = csrf_client.get("/community/activities/")

        self.assertEqual(page_response.status_code, 200)
        self.assertIn("csrftoken", csrf_client.cookies)
        csrf_token = csrf_client.cookies["csrftoken"].value
        comment_response = csrf_client.post(
            f"/profile/activity-stories/{story.pk}/comments/",
            {
                "content": "携带社区页面签发的 CSRF token",
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(comment_response.status_code, 302)
        self.assertTrue(
            ParticipationStoryComment.objects.filter(
                story=story,
                author=self.visitor,
                content="携带社区页面签发的 CSRF token",
            ).exists()
        )

    def test_skill_interactions_reject_external_next_and_enforce_csrf(self):
        selection = PersonProfileTag.objects.create(
            person=self.person,
            tag=self.skill_only_tag,
            kind=PersonProfileTag.Kind.SKILL,
            description="安全互动技能",
        )
        self.client.force_login(self.visitor_user)
        response = self.client.post(
            f"/profile/skill-stories/{selection.pk}/like/",
            {"next": "https://example.com/phishing"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("example.com", response["Location"])

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.visitor_user)
        self.assertEqual(
            csrf_client.post(
                f"/profile/skill-stories/{selection.pk}/comments/",
                {"content": "缺少 CSRF"},
            ).status_code,
            403,
        )

    def test_activity_detail_shows_only_that_activity_history_uploads(self):
        participation = self._create_activity_participation(
            "历史上传所属活动", Participation.AttendStatus.ATTENDED
        )
        other_participation = self._create_activity_participation(
            "另一个活动", Participation.AttendStatus.ATTENDED
        )
        participation.activity.status = Activity.Status.END
        participation.activity.save(update_fields=["status"])
        ActivityPhoto.objects.create(
            activity=participation.activity,
            type=ActivityPhoto.PhotoType.ANNOUNCE,
            image="assets/img/announcepics/1.JPG",
        )
        ParticipationStory.objects.create(
            participation=participation, description="本活动的历史上传"
        )
        ParticipationStory.objects.create(
            participation=other_participation, description="其他活动的历史上传"
        )

        self.client.force_login(self.visitor_user)
        response = self.client.get(f"/viewActivity/{participation.activity_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", self.client.cookies)
        self.assertContains(response, "活动历史上传")
        self.assertContains(response, "本活动的历史上传")
        self.assertNotContains(response, "其他活动的历史上传")
