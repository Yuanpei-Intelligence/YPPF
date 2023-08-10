from django.contrib import admin

from feedback.models import (
    Feedback,
    FeedbackType,
)

# Register your models here.
@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["type", "title", "person", "org", "feedback_time",]
    search_fields = ("person__name", "org__oname",)


@admin.register(FeedbackType)
class FeedbackTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "org_type", "org",]
    search_fields = ("name", "org_type", "org",)
