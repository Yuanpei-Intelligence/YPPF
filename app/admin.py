from app.models import *
from boottest.admin_utils import *

from datetime import datetime
from django.contrib import admin
from django.db import transaction
from django.utils.safestring import mark_safe

# Register your models here.
admin.site.site_title = '元培智慧校园管理后台'
admin.site.site_header = '元培智慧校园 - 管理后台'
# 合并后只需声明一次
# admin.site.site_title = '元培成长档案管理后台'
# admin.site.site_header = '元培成长档案 - 管理后台'


# 通用内联模型
@readonly_inline
class PositionInline(admin.TabularInline):
    model = Position
    classes = ['collapse']
    ordering = ['-id']
    fields = [
        'person', 'org',
        'in_year', 'in_semester',
        'is_admin', 'pos', 'status',
    ]
    show_change_link = True

@readonly_inline
class ParticipantInline(admin.TabularInline):
    model = Participant
    classes = ['collapse']
    ordering = ['-activity_id']
    fields = ['activity_id', 'person_id', 'status']
    show_change_link = True

@readonly_inline
class CourseParticipantInline(admin.TabularInline):
    model = CourseParticipant
    classes = ['collapse']
    ordering = ['-id']
    fields = ['course', 'person', 'status']
    show_change_link = True


# 后台模型
@admin.register(NaturalPerson)
class NaturalPersonAdmin(admin.ModelAdmin):
    fieldsets = (
        [
            "Common Attributes",
            {
                "fields": (
                    "person_id", "name", "nickname", "gender", "identity", "status",
                    "YQPoint", "YQPoint_Bonus", "bonusPoint", "wechat_receive_level",
                    "accept_promote", "active_score",
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

    inlines = [PositionInline, ParticipantInline, CourseParticipantInline]

    def view_on_site(self, obj: NaturalPerson):
        return obj.get_absolute_url(absolute=True)

    actions = [
        'YQ_send',
        'set_student', 'set_teacher',
        'set_graduate', 'set_ungraduate',
        'all_subscribe', 'all_unsubscribe',
        ]

    @as_action("发放元气值")
    def YQ_send(self, request, queryset):
        from app.scheduler_func import distribute_YQPoint_per_month
        distribute_YQPoint_per_month()
        return self.message_user(request=request,
                                message='发放成功!')
    
    @as_action("设为 学生", update=True)
    def set_student(self, request, queryset):
        queryset.update(identity=NaturalPerson.Identity.STUDENT)
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设为 老师", update=True)
    def set_teacher(self, request, queryset):
        queryset.update(identity=NaturalPerson.Identity.TEACHER)
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设为 已毕业", update=True)
    def set_graduate(self, request, queryset):
        queryset.update(status=NaturalPerson.GraduateStatus.GRADUATED)
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设为 未毕业", update=True)
    def set_ungraduate(self, request, queryset):
        queryset.update(status=NaturalPerson.GraduateStatus.UNDERGRADUATED)
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设置 全部订阅")
    def all_subscribe(self, request, queryset):
        for org in queryset:
            org.unsubscribers.clear()
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设置 取消订阅")
    def all_unsubscribe(self, request, queryset):
        orgs = list(Organization.objects.exclude(
            otype__otype_id=0).values_list('id', flat=True))
        for person in queryset:
            person.unsubscribers.set(orgs)
            person.save()
        return self.message_user(request=request,
                                 message='修改成功!已经取消所有非官方组织的订阅!')

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
    search_fields = ("organization_id__username", "oname", "otype__otype_name")
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

    inlines = [PositionInline]

    def view_on_site(self, obj: Organization):
        return obj.get_absolute_url(absolute=True)

    actions = ['all_subscribe', 'all_unsubscribe']

    @as_action("设置 全部订阅")
    def all_subscribe(self, request, queryset):
        for org in queryset:
            org.unsubscribers.clear()
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设置 全部不订阅")
    def all_unsubscribe(self, request, queryset):
        persons = list(NaturalPerson.objects.all().values_list('id', flat=True))
        for org in queryset:
            org.unsubscribers.set(persons)
            org.save()
        return self.message_user(request=request,
                                 message='修改成功!')


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ["person", "org", "pos", "pos_name", "is_admin"]
    search_fields = ("person__name", "org__oname", 'org__otype__otype_name')
    list_filter = ('pos', 'is_admin', 'org__otype')
    autocomplete_fields = ['person', 'org']

    def pos_name(self, obj):
        return obj.org.otype.get_name(obj.pos)
    pos_name.short_description = "职务名称"

    actions = ['demote', 'promote', 'to_member', 'to_manager', 'set_admin', 'set_not_admin']

    @as_action("职务等级 增加(降职)", update=True)
    def demote(self, request, queryset):
        for pos in queryset:
            pos.pos += 1
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("职务等级 降低(升职)", update=True)
    def promote(self, request, queryset):
        for pos in queryset:
            pos.pos = min(0, pos.pos - 1)
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("设为成员", update=True)
    def to_member(self, request, queryset):
        for pos in queryset:
            pos.pos = pos.org.otype.get_length()
            pos.is_admin = False
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功, 并收回了管理权限!')

    @as_action("设为负责人", update=True)
    def to_manager(self, request, queryset):
        for pos in queryset:
            pos.pos = 0
            pos.is_admin = True
            pos.save()
        return self.message_user(request=request,
                                 message='修改成功, 并赋予了管理权限!')

    @as_action("赋予 管理权限", update=True)
    def set_admin(self, request, queryset):
        queryset.update(is_admin=True)
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("收回 管理权限", update=True)
    def set_not_admin(self, request, queryset):
        queryset.update(is_admin=False)
        return self.message_user(request=request,
                                 message='修改成功!')


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ["title", 'id', "organization_id",
                    "status", "participant_diaplay",
                    "publish_time", "start", "end",]
    search_fields = ('id', "title", "organization_id__oname",
                     "current_participants",)
    
    class ErrorFilter(admin.SimpleListFilter):
        title = '错误状态' # 过滤标题显示为"以 错误状态"
        parameter_name = 'wrong_status' # 过滤器使用的过滤字段
    
        def lookups(self, request, model_admin):
            '''针对字段值设置过滤器的显示效果'''
            return (
                ('all', '全部错误状态'),
                ('not_waiting', '未进入 等待中 状态'),
                ('not_processing', '未进入 进行中 状态'),
                ('not_end', '未进入 已结束 状态'),
                ('review_end', '已结束的未审核'),
                ('normal', '正常'),
            )
        
        def queryset(self, request, queryset):
            '''定义过滤器的过滤动作'''
            now = datetime.now()
            error_id_set = set()
            activate_queryset = queryset.exclude(
                    status__in=[
                        Activity.Status.REVIEWING,
                        Activity.Status.CANCELED,
                        Activity.Status.REJECT,
                        Activity.Status.ABORT,
                    ])
            if self.value() in ['not_waiting', 'all', 'normal']:
                error_id_set.update(activate_queryset.exclude(
                    status=Activity.Status.WAITING).filter(
                    apply_end__lte=now,
                    start__gt=now,
                    ).values_list('id', flat=True))
            if self.value() in ['not_processing', 'all', 'normal']:
                error_id_set.update(activate_queryset.exclude(
                    status=Activity.Status.PROGRESSING).filter(
                    start__lte=now,
                    end__gt=now,
                    ).values_list('id', flat=True))
            if self.value() in ['not_end', 'all', 'normal']:
                error_id_set.update(activate_queryset.exclude(
                    status=Activity.Status.END).filter(
                    end__lte=now,
                    ).values_list('id', flat=True))
            if self.value() in ['review_end', 'all', 'normal']:
                error_id_set.update(queryset.filter(
                    status=Activity.Status.REVIEWING,
                    end__lte=now,
                    ).values_list('id', flat=True))

            if self.value() == 'normal':
                return queryset.exclude(id__in=error_id_set)
            elif self.value() is not None:
                return queryset.filter(id__in=error_id_set)
            return queryset
    
    list_filter = (
        "status",
        'year', 'semester', 'category',
        "organization_id__otype",
        "inner", "need_checkin", "valid", "source",
        ErrorFilter,
        'endbefore',
        "publish_time", 'start', 'end',
    )
    date_hierarchy = 'start'

    def participant_diaplay(self, obj):
        return f'{obj.current_participants}/{"无限" if obj.capacity == 10000 else obj.capacity}'
    participant_diaplay.short_description = "报名情况"

    inlines = [ParticipantInline]

    actions = []

    @as_action("更新 报名人数", actions, update=True)
    def refresh_count(self, request, queryset):
        for activity in queryset:
            activity.current_participants = Participant.objects.filter(
                activity_id=activity, status__in=[
                    Participant.AttendStatus.ATTENDED,
                    Participant.AttendStatus.UNATTENDED,
                    Participant.AttendStatus.APLLYSUCCESS,
                    ]).count()
            activity.save()
        return self.message_user(request=request, message='修改成功!')
    
    @as_action('设为 普通活动', actions, update=True)
    def set_normal_category(self, request, queryset):
        queryset.update(category=Activity.ActivityCategory.NORMAL)
        return self.message_user(request=request, message='修改成功!')

    @as_action('设为 课程活动', actions, update=True)
    def set_course_category(self, request, queryset):
        queryset.update(category=Activity.ActivityCategory.COURSE)
        return self.message_user(request=request, message='修改成功!')

    @as_action("进入 等待中 状态", actions)
    def to_waiting(self, request, queryset):
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能修改一个活动状态!', level='error')
        activity = queryset[0]
        from app.activity_utils import changeActivityStatus
        changeActivityStatus(activity.id, Activity.Status.APPLYING, Activity.Status.WAITING)
        try:
            from app.scheduler_func import scheduler
            scheduler.remove_job(f'activity_{activity.id}_{Activity.Status.WAITING}')
            return self.message_user(request=request,
                                    message='修改成功, 并移除了定时任务!')
        except:
            return self.message_user(request=request,
                                    message='修改成功!')
    
    @as_action("进入 进行中 状态", actions)
    def to_processing(self, request, queryset):
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能修改一个活动状态!', level='error')
        activity = queryset[0]
        from app.activity_utils import changeActivityStatus
        changeActivityStatus(activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING)
        try:
            from app.scheduler_func import scheduler
            scheduler.remove_job(f'activity_{activity.id}_{Activity.Status.PROGRESSING}')
            return self.message_user(request=request,
                                    message='修改成功, 并移除了定时任务!')
        except:
            return self.message_user(request=request, message='修改成功!')
    
    @as_action("进入 已结束 状态", actions)
    def to_end(self, request, queryset):
        if len(queryset) != 1:
            return self.message_user(
                request=request, message='一次只能修改一个活动状态!', level='error')
        activity = queryset[0]
        from app.activity_utils import changeActivityStatus
        changeActivityStatus(activity.id, Activity.Status.PROGRESSING, Activity.Status.END)
        try:
            from app.scheduler_func import scheduler
            scheduler.remove_job(f'activity_{activity.id}_{Activity.Status.END}')
            return self.message_user(request=request,
                                    message='修改成功, 并移除了定时任务!')
        except:
            return self.message_user(request=request, message='修改成功!')

    @as_action("取消 定时任务", actions)
    def cancel_scheduler(self, request, queryset):
        success_list = []
        failed_list = []
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


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ["id", 'activity_id', "person_id", "status",]
    search_fields = ('id','activity_id__id',
                     "activity_id__title", "person_id__name",)
    list_filter =   ("status", 'activity_id__category',
                     'activity_id__year', 'activity_id__semester',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "receiver", "sender", "title", "start_time"]
    search_fields = ('id', "receiver__username", "sender__username", 'title')
    list_filter = ('start_time', 'status', 'typename', "finish_time")

    actions = [
        'set_delete',
        'republish',
        'republish_bulk_at_promote', 'republish_bulk_at_message',
        ]

    @as_action("设置状态为 删除", update=True)
    def set_delete(self, request, queryset):
        queryset.update(status=Notification.Status.DELETE)
        return self.message_user(request=request,
                                 message='修改成功!')

    @as_action("重发 单个通知")
    def republish(self, request, queryset):
        if len(queryset) != 1:
            return self.message_user(request=request,
                                     message='一次只能重发一个通知!',
                                     level='error')
        notification = queryset[0]
        from app.wechat_send import publish_notification, WechatApp
        if not publish_notification(
            notification,
            app=WechatApp.NORMAL,
            ):
            return self.message_user(request=request,
                                     message='发送失败!请检查通知内容!',
                                     level='error')
        return self.message_user(request=request,
                                 message='已成功定时,将发送至默认窗口!')
    
    def republish_bulk(self, request, queryset, app):
        if not request.user.is_superuser:
            return self.message_user(request=request,
                                     message='操作失败,没有权限,请联系老师!',
                                     level='warning')
        if len(queryset) != 1:
            return self.message_user(request=request,
                                     message='一次只能选择一个通知!',
                                     level='error')
        bulk_identifier = queryset[0].bulk_identifier
        if not bulk_identifier:
            return self.message_user(request=request,
                                     message='该通知不存在批次标识!',
                                     level='error')
        try:
            from app.wechat_send import publish_notifications
        except Exception as e:
            return self.message_user(request=request,
                                     message=f'导入失败, 原因: {e}',
                                     level='error')
        if not publish_notifications(
            filter_kws={'bulk_identifier': bulk_identifier},
            app=app,
            ):
            return self.message_user(request=request,
                                     message='发送失败!请检查通知内容!',
                                     level='error')
        return self.message_user(request=request,
                                 message=f'已成功定时!标识为{bulk_identifier}')
    republish_bulk.short_description = "错误的重发操作"

    @as_action("重发 所在批次 于 订阅窗口")
    def republish_bulk_at_promote(self, request, queryset):
        try:
            from app.wechat_send import WechatApp
            app = WechatApp._PROMOTE
        except Exception as e:
            return self.message_user(request=request,
                                     message=f'导入失败, 原因: {e}',
                                     level='error')
        return self.republish_bulk(request, queryset, app)

    @as_action("重发 所在批次 于 消息窗口")
    def republish_bulk_at_message(self, request, queryset):
        try:
            from app.wechat_send import WechatApp
            app = WechatApp._MESSAGE
        except Exception as e:
            return self.message_user(request=request,
                                     message=f'导入失败, 原因: {e}',
                                     level='error')
        return self.republish_bulk(request, queryset, app)


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

    @as_action("随机设置背景颜色", superuser=False, update=True)
    def change_color(self, request, queryset):
        for wish in queryset:
            wish.background = Wishes.rand_color()
            wish.save()
        return self.message_user(request=request,
                                 message='修改成功!已经随机设置了背景颜色!')
        

@admin.register(ModifyRecord)
class ModifyRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "usertype", "name", 'time']
    search_fields = ('id', "user__username", "name")
    list_filter = ('time', 'usertype')

    actions = ['get_rank']

    @as_action("查询排名", superuser=False)
    def get_rank(self, request, queryset):
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


@admin.register(ModifyPosition)
class ModifyPositionAdmin(admin.ModelAdmin):
    list_display = ["id", "person", "org", "apply_type", "status"]
    search_fields = ("org__oname", "person__name")
    list_filter = ("apply_type", 'status', "org__otype", 'time', 'modify_time',)


@admin.register(ModifyOrganization)
class ModifyOrganizationAdmin(admin.ModelAdmin):
    list_display = ["id", "oname", "otype", "pos", "get_poster_name", "status"]
    search_fields = ("id", "oname", "otype__otype_name", "pos__username",)
    list_filter = ('status', "otype", 'time', 'modify_time',)
    ModifyOrganization.get_poster_name.short_description = "申请者"


@admin.register(Reimbursement)
class ReimbursementAdmin(admin.ModelAdmin):
    list_display = ["related_activity", "id", "pos", "get_poster_name",
                    "amount",
                    "examine_teacher", "time", "status",]
    search_fields = ("id", "related_activity__title",
                    "related_activity__organization_id__oname", "pos__username",
                    'examine_teacher__name',)
    list_filter = ('status', 'time', 'modify_time',)
    Reimbursement.get_poster_name.short_description = "申请者"


@admin.register(TransferRecord)
class TransferRecordAdmin(admin.ModelAdmin):
    list_display = ["proposer", "recipient", "corres_act",
                    "amount", "rtype", "status",
                    "start_time",]
    search_fields = ("proposer__username", "recipient__username",
                    "corres_act__title",)
    list_filter = ("status", "rtype", "start_time", "finish_time",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "organization",
        "type",
        "participant_diaplay",
        "status",
    ]
    search_fields = (
        "name", "organization__oname",
        'classroom', 'teacher',
    )
    list_filter = ("year", "semester", "type", "status",)
    autocomplete_fields = ['organization']

    class CourseTimeInline(admin.TabularInline):
        model = CourseTime
        classes = ['collapse']
        extra = 1

    inlines = [CourseTimeInline, CourseParticipantInline]
    
    def participant_diaplay(self, obj):
        return f'{obj.current_participants}/{"无限" if obj.capacity == 10000 else obj.capacity}'
    participant_diaplay.short_description = "报名情况"

    actions = []

    @as_action("更新课程状态", actions)
    def refresh_status(self, request, queryset):
        from app.course_utils import register_selection
        register_selection()
        return self.message_user(request=request,
                                 message='已设置定时任务!')

    @as_action("更新课程状态 延迟2分钟", actions)
    def refresh_status_delay2(self, request, queryset):
        from app.course_utils import register_selection
        from datetime import timedelta
        register_selection(wait_for=timedelta(minutes=2))
        return self.message_user(request=request,
                                 message='已设置定时任务!')


@admin.register(CourseParticipant)
class CourseParticipantAdmin(admin.ModelAdmin):
    list_display = ["course", "person", "status",]
    search_fields = ("course__name", "person__name",)
    autocomplete_fields = ['course', 'person']


@admin.register(CourseRecord)
class CourseRecordAdmin(admin.ModelAdmin):
    list_display = [
        'get_course_name', 'person',
        'year', 'semester',
        'attend_times', 'total_hours',
        'invalid',
    ]
    search_fields = (
        'course__name', 'extra_name',
        'person__name', 'person__person_id__username',
    )
    class TypeFilter(admin.SimpleListFilter):
        title = '学时类别'
        parameter_name = 'type' # 过滤器使用的过滤字段
    
        def lookups(self, request, model_admin):
            '''针对字段值设置过滤器的显示效果'''
            # 自带一个None, '全部'
            return (
                ('null', '无'),
                ('any', '任意'),
            ) + tuple(Course.CourseType.choices)
        
        def queryset(self, request, queryset):
            '''定义过滤器的过滤动作'''
            if self.value() == 'null':
                return queryset.filter(course__isnull=True)
            elif self.value() == 'any':
                return queryset.exclude(course__isnull=True)
            elif self.value() in map(str, Course.CourseType.values):
                return queryset.filter(course__type=self.value())
            return queryset
    list_filter = (TypeFilter, 'year', 'semester', 'invalid')

    autocomplete_fields = ['person', 'course']

    actions = []

    @as_action('更新来源名称', actions, update=True)
    def update_extra_name(self, request, queryset):
        records = queryset.filter(course__isnull=False)
        for record in records.select_related('course'):
            record.extra_name = record.course.name
            record.save()
        return self.message_user(request=request, message='已更新关联学时名称!')

    @as_action("设置为 无效学时", actions, update=True)
    def set_invalid(self, request, queryset):
        queryset.update(invalid=True)
        return self.message_user(request=request, message='修改成功!')

    @as_action("设置为 有效学时", actions, update=True)
    def set_valid(self, request, queryset):
        queryset.update(invalid=False)
        return self.message_user(request=request, message='修改成功!')


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["type", "title", "person", "org", "feedback_time",]
    search_fields = ("person__name", "org__oname",)

@admin.register(FeedbackType)
class FeedbackTypeAdmin(admin.ModelAdmin):
    list_display = ["name","org_type","org",]
    search_fields =  ("name","org_type","org",)


@admin.register(PageLog)
class PageLogAdmin(admin.ModelAdmin):
    list_display = ["user", "type", "page", "time"]
    list_filter = ["type", "page", 'time', "platform", "explore_name", "explore_version"]
    search_fields =  ["user__username", "page"]
    date_hierarchy = "time"

@admin.register(ModuleLog)
class ModuleLogAdmin(admin.ModelAdmin):
    list_display = ["user", "type", "page", "module_name", "time"]
    list_filter = ["type", "page", "module_name", 'time', "platform", "explore_name", "explore_version"]
    search_fields = ["user__username", "page", "module_name"]
    date_hierarchy = "time"


admin.site.register(YQPointDistribute)
admin.site.register(QandA)
admin.site.register(OrganizationTag)
admin.site.register(Comment)
admin.site.register(CommentPhoto)
