from django.contrib import admin
from django.utils.safestring import mark_safe
from app.models import *

# Register your models here.
admin.site.site_title = '元培成长档案管理后台'
admin.site.site_header = '元培成长档案 - 管理后台'


@admin.register(NaturalPerson)
class NaturalPersonAdmin(admin.ModelAdmin):
    fieldsets = (
        [
            "Commom Attributes",
            {
                "fields": (
                    "person_id", "name", "nickname", "gender", "identity", "status",
                    "YQPoint", "YQPoint_Bonus", "bonusPoint", "wechat_receive_level",
                    "stu_id_dbonly",
                    ),
            }
        ],
        [
            "Student Attributes",
            {
                "classes": ("collapse",),
                "fields": (
                    "stu_grade", "stu_class", "stu_dorm", "stu_major",
                    "show_gender", "show_email", "show_tel", "show_major", "show_dorm",
                    "show_nickname", "show_birthday", 
                    ),
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
    readonly_fields = ("stu_id_dbonly",)
    list_filter = (
        "status", "identity",
        "first_time_login", "wechat_receive_level",
        "stu_grade", "stu_class",
        )

    actions = [
        'YQ_send',
        'set_student', 'set_teacher',
        'set_graduate', 'set_ungraduate',
        'all_subscribe', 'all_unsubscribe',
        ]

    def YQ_send(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        try:
            from app.scheduler_func import distribute_YQPoint_per_month
            distribute_YQPoint_per_month()
            return self.message_user(request=request,
                                    message='发放成功!')
        except Exception as e:
            return self.message_user(request=request,
                                     message=f'操作失败, 原因为: {e}',
                                     level='error')
    YQ_send.short_description = "发放元气值"
    
    def set_student(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        queryset.update(identity=NaturalPerson.Identity.STUDENT)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_student.short_description = "设为 学生"

    def set_teacher(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        queryset.update(identity=NaturalPerson.Identity.TEACHER)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_teacher.short_description = "设为 老师"

    def set_graduate(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        queryset.update(status=NaturalPerson.GraduateStatus.GRADUATED)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_graduate.short_description = "设为 已毕业"

    def set_ungraduate(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        queryset.update(status=NaturalPerson.GraduateStatus.UNDERGRADUATED)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_ungraduate.short_description = "设为 未毕业"

    def all_subscribe(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for org in queryset:
            org.unsubscribers.clear()
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    all_subscribe.short_description = "设置 全部订阅"

    def all_unsubscribe(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        orgs = list(Organization.objects.exclude(
            otype__otype_id=0).values_list('id', flat=True))
        for person in queryset:
            person.unsubscribers.set(orgs)
            person.save()
        return self.message_user(request=request,
                                 message='修改成功!已经取消所有非官方组织的订阅!')
    all_unsubscribe.short_description = "设置 取消订阅"

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
    search_fields = ("otype_name", "otype_id", "incharge__name", "job_name_list")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["organization_id", "oname", "otype", "Managers"]
    search_fields = ("oname", "otype__otype_id", "otype__otype_name")
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
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for org in queryset:
            org.unsubscribers.clear()
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    all_subscribe.short_description = "设置 全部订阅"

    def all_unsubscribe(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
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
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for pos in queryset:
            pos.pos += 1
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    demote.short_description = "职务等级 增加(降职)"

    def promote(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for pos in queryset:
            pos.pos = min(0, pos.pos - 1)
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功!')
    promote.short_description = "职务等级 降低(升职)"

    def to_member(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for pos in queryset:
            pos.pos = pos.org.otype.get_length()
            pos.is_admin = False
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功, 并收回了管理权限!')
    to_member.short_description = "设为成员"

    def to_manager(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for pos in queryset:
            pos.pos = 0
            pos.is_admin = True
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功, 并赋予了管理权限!')
    to_manager.short_description = "设为负责人"

    def set_admin(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        queryset.update(is_admin = True)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_admin.short_description = "赋予 管理权限"

    def set_not_admin(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        queryset.update(is_admin = False)
        return self.message_user(request=request,
                                 message='修改成功!')
    set_not_admin.short_description = "收回 管理权限"


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ["title", 'id', "organization_id",
                    "status", "participant_diaplay",
                    "publish_time", "start", "end",]
    search_fields = ('id', "title", "organization_id__oname",
                     "current_participants",)
    list_filter =   (
                        "status", "inner", "need_checkin", "valid",
                        "organization_id__otype", "source",
                        'endbefore', "capacity", "year",
                        "publish_time", 'start', 'end',
                    )
    date_hierarchy = 'start'

    def participant_diaplay(self, obj):
        return f'{obj.current_participants}/{"无限" if obj.capacity == 10000 else obj.capacity}'
    participant_diaplay.short_description = "报名情况"

    actions = [
                'refresh_count',
                'to_waiting', 'to_processing', 'to_end',
                'cancel_scheduler'
        ]

    def refresh_count(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        for activity in queryset:
            activity.current_participants = Participant.objects.filter(
                activity_id=activity, status__in=[
                    Participant.AttendStatus.ATTENDED,
                    Participant.AttendStatus.UNATTENDED,
                    Participant.AttendStatus.APLLYSUCCESS,
                    ]).count()
            activity.save()
        return self.message_user(request=request, message='修改成功!')
    refresh_count.short_description = "更新 报名人数"

    def to_waiting(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能修改一个活动状态!', level='error')
        activity = queryset[0]
        try:
            from app.scheduler_func import changeActivityStatus
            changeActivityStatus(activity.id, Activity.Status.APPLYING, Activity.Status.WAITING)
            try:
                from app.scheduler_func import scheduler
                scheduler.remove_job(f'activity_{activity.id}_{Activity.Status.WAITING}')
                return self.message_user(request=request,
                                        message='修改成功, 并移除了定时任务!')
            except:
                return self.message_user(request=request,
                                        message='修改成功!')
        except Exception as e:
            return self.message_user(
                request=request, message=f'操作失败, 原因: {e}', level='error')
    to_waiting.short_description = "进入 等待中 状态"
    
    def to_processing(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能修改一个活动状态!', level='error')
        activity = queryset[0]
        try:
            from app.scheduler_func import changeActivityStatus
            changeActivityStatus(activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING)
            try:
                from app.scheduler_func import scheduler
                scheduler.remove_job(f'activity_{activity.id}_{Activity.Status.PROGRESSING}')
                return self.message_user(request=request,
                                        message='修改成功, 并移除了定时任务!')
            except:
                return self.message_user(request=request,
                                        message='修改成功!')
        except Exception as e:
            return self.message_user(
                request=request, message=f'操作失败, 原因: {e}', level='error')
    to_processing.short_description = "进入 进行中 状态"
    
    def to_end(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能修改一个活动状态!', level='error')
        activity = queryset[0]
        try:
            from app.scheduler_func import changeActivityStatus
            changeActivityStatus(activity.id, Activity.Status.PROGRESSING, Activity.Status.END)
            try:
                from app.scheduler_func import scheduler
                scheduler.remove_job(f'activity_{activity.id}_{Activity.Status.END}')
                return self.message_user(request=request,
                                        message='修改成功, 并移除了定时任务!')
            except:
                return self.message_user(request=request,
                                        message='修改成功!')
        except Exception as e:
            return self.message_user(
                request=request, message=f'操作失败, 原因: {e}', level='error')
    to_end.short_description = "进入 已结束 状态"

    def cancel_scheduler(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        success_list = []
        failed_list = []
        try:
            from app.scheduler_func import scheduler
            CANCEL_STATUSES = [
                'remind',
                Activity.Status.END,
                Activity.Status.PROGRESSING,
                Activity.Status.WAITING,
            ]
            for activity in queryset:
                failed_statuses = []
                for status in CANCEL_STATUSES:
                    try:
                        scheduler.remove_job(f'activity_{activity.id}_{status}')
                    except:
                        failed_statuses.append(status)
                if failed_statuses:
                    if len(failed_statuses) != len(CANCEL_STATUSES):
                        failed_list.append(f'{activity.id}: {",".join(failed_statuses)}')
                    else:
                        failed_list.append(f'{activity.id}')
                else:
                    success_list.append(f'{activity.id}')
            
            msg = f'成功取消{len(success_list)}项活动的定时任务!' if success_list else '未能完全取消任何任务'
            if failed_list:
                msg += f'\n{len(failed_list)}项活动取消失败：\n{";".join(failed_list)}'
            return self.message_user(request=request, message=msg)
        except Exception as e:
            return self.message_user(
                request=request, message=f'操作失败, 原因: {e}', level='error')
    cancel_scheduler.short_description = "取消 定时任务"


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ["id", 'activity_id', "person_id", "status",]
    search_fields = ('id', "activity_id__title", "person_id__name",)
    list_filter =   ("status", )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "receiver", "sender", "title", "start_time"]
    search_fields = ('id', "receiver__username", "sender__username", 'title')
    list_filter = ('start_time', 'status', 'typename', "finish_time")

    actions = ['set_delete']

    def set_delete(self, request, queryset):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
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

    actions = ['change_color']

    def change_color(self, request, queryset):
        # if not request.user.is_superuser:
        #     return self.message_user(request=request,
        #                              message='操作失败,没有权限,请联系老师!',
        #                              level='warning')
        for wish in queryset:
            wish.background = Wishes.rand_color()
            wish.save()
        return self.message_user(request=request,
                                 message='修改成功!已经随机设置了背景颜色!')
    change_color.short_description = "随机设置背景颜色"
        

@admin.register(ModifyRecord)
class ModifyRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "usertype", "name", 'time']
    search_fields = ('id', "user__username", "name")
    list_filter = ('time', 'usertype')

    actions = ['get_rank']

    def get_rank(self, request, queryset):
        # if not request.user.is_superuser:
        #     return self.message_user(request=request,
        #                              message='操作失败,没有权限,请联系老师!',
        #                              level='warning')
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能查询一个用户的排名!', level='error')
        try:
            record = queryset[0]
            usertype = record.usertype
            records = ModifyRecord.objects.filter(
                user=record.user, usertype=usertype)
            first = records.order_by('time')[0]
            rank = ModifyRecord.objects.filter(
                usertype=usertype,
                time__lte=first.time,
                ).values('user').distinct().count()
            return self.message_user(request=request,
                                    message=f'查询成功: {first.name}的排名为{rank}!')
        except Exception as e:
            return self.message_user(request=request,
                                    message=f'查询失败: {e}!', level='error')
    get_rank.short_description = "查询排名"

@admin.register(ModifyPosition)
class ModifyPositionAdmin(admin.ModelAdmin):
    list_display = ["person","org","apply_type", "status"]
    search_fields = ("org__oname", "person__name")


admin.site.register(ModifyOrganization)


admin.site.register(TransferRecord)

admin.site.register(YQPointDistribute)
admin.site.register(Reimbursement)
admin.site.register(QandA)

