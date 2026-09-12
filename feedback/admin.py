from django.contrib import admin

from feedback.models import (
    Feedback,
    FeedbackType,
)

# Register your models here.
@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["type", "title", "person", "org", "feature_key", "feedback_time",]
    list_filter = ["feature_key"]
    search_fields = ("person__name", "org__oname", "feature_key",)


@admin.register(FeedbackType)
class FeedbackTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "org_type", "org",]
    search_fields = ("name", "org_type__otype_name", "org__oname",)
