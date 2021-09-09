from django.contrib import admin
from django.utils.safestring import mark_safe
from app.models import *

# Register your models here.
admin.site.site_title = '元培成长档案管理后台'
admin.site.site_header = '元培成长档案 - 管理后台'


@admin.register(NaturalPerson)
class NaturalPersonAdmin(admin.ModelAdmin):
    fieldsets = (
        ["Commom Attributes", {"fields": (
            "person_id", "name", "nickname", "gender", "identity",
            "YQPoint", "YQPoint_Bonus", "wechat_receive_level")}],
        [
            "Student Attributes",
            {
                "classes": ("collapse",),
                "fields": ("stu_grade", "stu_dorm", "stu_class", "stu_major",
                "show_gender", "show_email", "show_tel", "show_major", "show_dorm"),
                # "show_nickname"
            },
        ],
    )
    list_display = [
        "person_id",
        "name",
        "identity",
        "first_time_login",
    ]
    search_fields = ("person_id__username", "name")
    list_filter = ("stu_grade", "status", "identity", "first_time_login", "wechat_receive_level")

@admin.register(Freshman)
class FreshmanAdmin(admin.ModelAdmin):
    list_display = [
        "sid",
        "name",
        "place",
        "grade",
        "status",
    ]
    search_fields = ("sid", "name")
    list_filter = ("status", "grade", "place")


@admin.register(OrganizationType)
class OrganizationTypeAdmin(admin.ModelAdmin):
    list_display = ["otype_id", "otype_name", "incharge", "job_name_list", "control_pos_threshold"]
    search_fields = ("oname", "otype", "incharge__name", "job_name_list")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["organization_id", "oname", "otype", "Managers"]
    search_fields = ("oname", "otype")
    list_filter = ("otype", )

    def Managers(self, obj):
        display = ''
        all_pos = sorted(Position.objects.activated().filter(
                org=obj, is_admin=True).values_list(
                    'pos', flat=True).distinct())
        for pos in all_pos:
            managers = Position.objects.activated().filter(
                org=obj, pos=pos, is_admin=True)
            if managers:
                display += f'{obj.otype.get_name(pos)}：'
                names = managers.values_list('person__name', flat=True)
                display += f"<li>{'、'.join(names)}</li>"
        if not display:
            display = '暂无'
        return mark_safe(display)
    Managers.short_description = "管理者"

    actions = ['all_subscribe', 'all_unsubscribe']

    def all_subscribe(self, request, queryset):
        for org in queryset:
            org.unsubscribers.clear()
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    all_subscribe.short_description = "设置 全部订阅"

    def all_unsubscribe(self, request, queryset):
        persons = list(NaturalPerson.objects.all().values_list('id', flat=True))
        for org in queryset:
            org.unsubscribers.set(persons)
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    all_unsubscribe.short_description = "设置 全部不订阅"


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ["person", "org", "pos", "pos_name", "is_admin"]
    search_fields = ("person__name", "org__oname", 'org__otype__otype_name')
    list_filter = ('pos', 'is_admin', 'org__otype')

    def pos_name(self, obj):
        return obj.org.otype.get_name(obj.pos)
    pos_name.short_description = "职务名称"

    actions = ['demote', 'promote', 'to_member', 'to_manager', 'set_admin', 'set_not_admin']

    def demote(self, request, queryset):
        for pos in queryset:
            pos.pos += 1
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    demote.short_description = "职务等级 增加(降职)"

    def promote(self, request, queryset):
        for pos in queryset:
            pos.pos = min(0, pos.pos - 1)
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    promote.short_description = "职务等级 降低(升职)"

    def to_member(self, request, queryset):
        for pos in queryset:
            pos.pos = pos.org.otype.get_length()
            pos.is_admin = False
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功, 并收回了管理权限!')
    to_member.short_description = "设为成员"

    def to_manager(self, request, queryset):
        for pos in queryset:
            pos.pos = 0
            pos.is_admin = True
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功, 并赋予了管理权限!')
    to_manager.short_description = "设为负责人"

    def set_admin(self, request, queryset):
        queryset.update(is_admin = True)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_admin.short_description = "赋予 管理权限"

    def set_not_admin(self, request, queryset):
        queryset.update(is_admin = False)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_not_admin.short_description = "收回 管理权限"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "receiver", "sender", "title", "start_time"]
    search_fields = ('id', "receiver__username", "sender__username", 'title')
    list_filter = ('start_time', 'status', 'typename', "finish_time")

    actions = ['set_delete']

    def set_delete(self, request, queryset):
        queryset.update(status = Notification.Status.DELETE)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_delete.short_description = "设置状态为 删除"


@admin.register(Help)
class HelpAdmin(admin.ModelAdmin):
    list_display = ["id", "title"]


@admin.register(Wishes)
class WishesAdmin(admin.ModelAdmin):
    list_display = ["id", "text", 'time', "background_display"]
    list_filter = ('time', 'background')
    
    def background_display(self, obj):
        return mark_safe(f'<span style="color: {obj.background};"><strong>{obj.background}</strong></span>')
    background_display.short_description = "背景颜色"

@admin.register(ModifyRecord)
class ModifyRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "usertype", "name", 'time']
    search_fields = ('id', "user__username", "name")
    list_filter = ('time', 'usertype')


admin.site.register(Activity)
admin.site.register(TransferRecord)

admin.site.register(YQPointDistribute)
