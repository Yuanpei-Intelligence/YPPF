"""Admin pages of the 北大账号 binding. Encrypted cookies are never shown."""
from django.contrib import admin

from pku_account.models import PkuAccount, PkuPortalSession


@admin.register(PkuAccount)
class PkuAccountAdmin(admin.ModelAdmin):
    list_display = [
        'pku_username', 'user', 'verified_at', 'last_login_at',
        'last_sync_at', 'login_failures', 'locked_until',
        'consent_timetable', 'consent_grades',
    ]
    list_filter = ['consent_timetable', 'consent_grades']
    search_fields = ['pku_username', 'user__username', 'user__name']
    raw_id_fields = ['user']
    readonly_fields = [
        'verified_at', 'last_login_at', 'last_sync_at',
        'consent_timetable_at', 'consent_grades_at', 'created_at',
    ]

    # A binding is only meaningful after a real IAAA login; create it through
    # the mini-program (services.login_and_bind), never by hand.
    def has_add_permission(self, request) -> bool:
        return False


@admin.register(PkuPortalSession)
class PkuPortalSessionAdmin(admin.ModelAdmin):
    list_display = [
        'account', 'created_at', 'last_ok_at', 'last_checked_at',
        'invalid', 'invalid_reason',
    ]
    list_filter = ['invalid']
    search_fields = ['account__pku_username', 'account__user__username']
    raw_id_fields = ['account']
    # The cookie jar is the session itself: never render it, not even
    # read-only. Sessions are only ever created by a portal login.
    exclude = ['cookies_encrypted']
    readonly_fields = ['created_at', 'last_ok_at', 'last_checked_at']

    def has_add_permission(self, request) -> bool:
        return False
