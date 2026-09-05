from django.contrib import admin
from django.utils.html import format_html
from birthboard.models import (
    BirthboardApprover,
    BirthboardContract,
    BirthboardParticipant,
    BirthboardRecord,
    BirthboardSecondApprover,
    ChangeRecord,
)

@admin.register(BirthboardApprover)
class BirthboardApproverAdmin(admin.ModelAdmin):
    # is_active：是否允许该审核员参与审核；reminder_enabled：是否接收自动重复审核提醒
    # 两者独立，均可在列表内直接勾选/取消，保存即生效。
    list_display = ("user", "is_active", "reminder_enabled", "created_at", "note")
    list_editable = ("is_active", "reminder_enabled")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    list_filter = ("is_active", "reminder_enabled")
    autocomplete_fields = ["user"]

@admin.register(BirthboardSecondApprover)
class BirthboardSecondApproverAdmin(admin.ModelAdmin):
    list_display = ("user", "is_active", "reminder_enabled", "created_at", "note")
    list_editable = ("is_active", "reminder_enabled")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    list_filter = ("is_active", "reminder_enabled")
    autocomplete_fields = ["user"]


class _ReadOnlyInline(admin.TabularInline):
    """只读内联基类：子记录仅用于查看，禁止新增/删除/编辑。"""
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BirthboardParticipantInline(_ReadOnlyInline):
    """投放参与者明细（送出人/寿星、角色、扣款状态等）。"""
    model = BirthboardParticipant
    fields = (
        "user", "role", "is_initiator", "cost", "status", "action_time",
    )


class ChangeRecordInline(_ReadOnlyInline):
    """投放变更审计记录（操作、前后状态、详情等）。"""
    model = ChangeRecord
    # created_at 为 auto_now_add（不可编辑），只能经 readonly_fields 展示
    fields = (
        "actor", "action", "before_status", "after_status", "detail",
    )
    readonly_fields = ("created_at",)


@admin.register(BirthboardRecord)
class BirthboardRecordAdmin(admin.ModelAdmin):
    """投放记录后台：以查看/检索为主，流程字段只读。

    状态、金额、审批与投放同步等字段的变更涉及退款、通知与屏幕同步，必须走
    业务入口（页面/任务），禁止在 admin 直接修改，避免绕过事务与审计。
    记录由业务流程创建，admin 不提供新增。
    """
    list_display = (
        "id",
        "receiver_name",
        "receiver_username",
        "date",
        "status",
        "per_cost",
        "is_anonymous",
        "thumbnail_preview",
        "created_at",
    )
    list_display_links = ("id", "receiver_name")
    list_filter = ("status", "date", "is_anonymous")
    search_fields = ("receiver_name", "receiver_username", "id")
    date_hierarchy = "date"
    # 详情页同时内联展示参与者明细与变更审计记录（只读）
    inlines = (BirthboardParticipantInline, ChangeRecordInline)
    readonly_fields = (
        "receiver_username",
        "mode",
        "per_cost",
        "status",
        "created_at",
        "first_approved",
        "first_approver",
        "first_approved_at",
        "second_approver",
        "second_approved_at",
        "display_takedown_pending",
    )

    @admin.display(description="缩略图")
    def thumbnail_preview(self, obj):
        """列表里直接预览海报缩略图，便于核对内容。"""
        if not obj.thumbnail:
            return "—"
        return format_html(
            '<img src="{}" height="40" style="border-radius:4px" />',
            obj.thumbnail.url,
        )

    def has_add_permission(self, request):
        return False


@admin.register(BirthboardContract)
class BirthboardContractAdmin(admin.ModelAdmin):
    list_display = ("user", "signed", "signed_at", "restricted_until")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    list_filter = ("signed",)
    autocomplete_fields = ["user"]
    actions = ["clear_restriction"]

    @admin.action(description="解除限制参与")
    def clear_restriction(self, request, queryset):
        """批量清除所选用户的 restricted_until，随时中止生效中的限制。"""
        updated = queryset.update(restricted_until=None)
        self.message_user(request, f"已解除 {updated} 名用户的限制参与。")
