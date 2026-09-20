import re

from django import forms
from django.core.exceptions import ValidationError

from app.models import ProfileTag, ProfileTagCategory


MAX_STORY_IMAGES = 6
MAX_STORY_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_STORY_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Validate a bounded list of real JPEG, PNG, or WebP images."""

    widget = MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        if len(files) > MAX_STORY_IMAGES:
            raise ValidationError(f"每次最多上传 {MAX_STORY_IMAGES} 张图片。")

        cleaned_files = []
        errors = []
        for uploaded_file in files:
            if uploaded_file.size > MAX_STORY_IMAGE_BYTES:
                errors.append(
                    ValidationError(
                        f"图片“{uploaded_file.name}”超过 5 MB。", code="file_too_large"
                    )
                )
                continue
            try:
                cleaned_file = super().clean(uploaded_file, initial)
            except ValidationError as exc:
                errors.extend(exc.error_list)
                continue
            image_format = getattr(getattr(cleaned_file, "image", None), "format", "")
            if image_format not in ALLOWED_STORY_IMAGE_FORMATS:
                errors.append(
                    ValidationError(
                        f"图片“{uploaded_file.name}”必须是 JPEG、PNG 或 WebP 格式。",
                        code="invalid_image_format",
                    )
                )
                continue
            cleaned_file.seek(0)
            cleaned_files.append(cleaned_file)

        if errors:
            raise ValidationError(errors)
        return cleaned_files


class ProfileStoryForm(forms.Form):
    """Shared input contract for a tag note or an activity note."""

    description = forms.CharField(required=False, max_length=500, strip=True)
    images = MultipleImageField(required=False)
    delete_images = forms.MultipleChoiceField(required=False)

    def __init__(self, *args, existing_images=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.existing_images = list(existing_images)
        self.fields["delete_images"].choices = [
            (str(image.pk), str(image.pk)) for image in self.existing_images
        ]

    def clean(self):
        cleaned_data = super().clean()
        deleted_ids = {int(value) for value in cleaned_data.get("delete_images", [])}
        remaining_count = sum(
            image.pk not in deleted_ids for image in self.existing_images
        )
        uploaded_count = len(cleaned_data.get("images", []))
        if remaining_count + uploaded_count > MAX_STORY_IMAGES:
            self.add_error(
                "images",
                f"每条记录最多保留 {MAX_STORY_IMAGES} 张图片，请先勾选要删除的旧图片。",
            )
        cleaned_data["delete_image_ids"] = deleted_ids
        return cleaned_data


class ActivityStoryCommentForm(forms.Form):
    content = forms.CharField(
        max_length=300,
        strip=True,
        error_messages={
            "required": "评论不能为空。",
            "max_length": "评论最多 300 字。",
        },
    )


class ProfileTagUpdateForm(forms.Form):
    """Validate a complete replacement of one person's visible profile tags."""

    interest_tags = forms.ModelMultipleChoiceField(
        queryset=ProfileTag.objects.none(), required=False
    )
    skill_tags = forms.ModelMultipleChoiceField(
        queryset=ProfileTag.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        visible_tags = ProfileTag.objects.filter(
            status=ProfileTag.Status.VISIBLE,
            category__is_active=True,
        )
        self.fields["interest_tags"].queryset = visible_tags.filter(
            applies_to__in=[
                ProfileTag.AppliesTo.INTEREST,
                ProfileTag.AppliesTo.BOTH,
            ]
        )
        self.fields["skill_tags"].queryset = visible_tags.filter(
            applies_to__in=[
                ProfileTag.AppliesTo.SKILL,
                ProfileTag.AppliesTo.BOTH,
            ]
        )

        self.root_categories = list(
            ProfileTagCategory.objects.filter(parent__isnull=True, is_active=True)
            .order_by("sort_order", "id")
        )
        for kind in ("interest", "skill"):
            for category in self.root_categories:
                self.fields[f"custom_{kind}_{category.pk}"] = forms.CharField(
                    required=False,
                    max_length=1024,
                )

    @staticmethod
    def _split_custom_tags(raw_value):
        values = re.split(r"[,，、;；\n]+", raw_value or "")
        result = []
        seen = set()
        for value in values:
            display_name = " ".join(value.strip().split())
            if not display_name:
                continue
            normalized_name = ProfileTag.normalize_name(display_name)
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            result.append(display_name)
        return result

    def clean(self):
        cleaned_data = super().clean()
        custom_tags = {"interest": [], "skill": []}

        for kind in custom_tags:
            for category in self.root_categories:
                field_name = f"custom_{kind}_{category.pk}"
                for tag_name in self._split_custom_tags(cleaned_data.get(field_name)):
                    if len(tag_name) > ProfileTag._meta.get_field("name").max_length:
                        self.add_error(field_name, f"“{tag_name}”超过 24 个字符。")
                        continue
                    custom_tags[kind].append((category.pk, tag_name))

            selected_count = len(cleaned_data.get(f"{kind}_tags", []))
            if selected_count + len(custom_tags[kind]) > 30:
                self.add_error(None, "兴趣和技能各自最多选择 30 个标签。")

        cleaned_data["custom_tags"] = custom_tags
        return cleaned_data
