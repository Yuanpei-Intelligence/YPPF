from django.contrib import admin
from django.db.models import Count

from generic.admin import UserAdmin
from rollout.models import Feature, PreviewMember


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = [
        'key', 'name', 'stage', 'percent', 'allow_user_count',
        'owner', 'review_date', 'updated_at',
    ]
    list_filter = ['stage']
    search_fields = ['key', 'name', 'owner']
    autocomplete_fields = ['allow_users']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = [
        (None, {
            'fields': ['key', 'name', 'description', 'owner', 'review_date'],
        }),
        ('开放范围', {
            'fields': ['stage', 'allow_users', 'audience', 'percent'],
            'description': (
                '阶段逐级放宽：内测只对白名单开放；体验再加上体验通道成员和定向人群；'
                '放量再按比例开放；全量对所有人开放。改为「关闭」立即对所有人关闭，'
                '白名单也不例外。保存后下一次请求即生效。'
            ),
        }),
        ('记录', {'fields': ['created_at', 'updated_at']}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _allow_user_count=Count('allow_users'))

    @admin.display(description='白名单人数', ordering='_allow_user_count')
    def allow_user_count(self, obj: Feature) -> int:
        return obj._allow_user_count  # type: ignore[attr-defined]


@admin.register(PreviewMember)
class PreviewMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'user_name', 'joined_at']
    list_select_related = ['user']
    search_fields = UserAdmin.suggest_search_fields('user')
    autocomplete_fields = ['user']
    readonly_fields = ['joined_at']

    @admin.display(description='名称', ordering='user__name')
    def user_name(self, obj: PreviewMember) -> str:
        return obj.user.name
