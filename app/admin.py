from datetime import datetime

from django.contrib import admin
from django.db.models import QuerySet
from django.utils.safestring import mark_safe

from utils.http.dependency import HttpRequest
from utils.models.query import sfilter, f
from utils.admin_utils import *
from app.models import *
from scheduler.cancel import remove_job
from app.YQPoint_utils import run_lottery
from app.org_utils import accept_modifyorg_submit

# 通用内联模型
@readonly_inline
class PositionInline(admin.TabularInline):
    model = Position
    classes = ['collapse']
    ordering = ['-id']
    fields = [
        'person', 'org',
        'year', 'semester',
        'is_admin', 'pos', 'status',
    ]
    show_change_link = True

@readonly_inline
class ParticipationInline(admin.TabularInline):
    model = Participation
    classes = ['collapse']
    ordering = ['-' + f(model.activity)]
    fields = [f(model.activity), f(model.person), f(model.status)]
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
    _m = NaturalPerson
    list_display = [
        f(_m.person_id),
        f(_m.name),
        f(_m.identity),
    ]
    search_fields = [f(_m.person_id, User.username), f(_m.name)]
    readonly_fields = [f(_m.stu_id_dbonly)]
    list_filter = [
        f(_m.status), f(_m.identity),
        f(_m.wechat_receive_level),
        f(_m.stu_grade), f(_m.stu_class),
    ]

    inlines = [PositionInline, ParticipationInline, CourseParticipantInline]

    def _show_by_option(self, obj: NaturalPerson | None, option: str, detail: str):
        if obj is None or getattr(obj, option):
            return option, detail
        return option

    def get_normal_fields(self, request, obj: NaturalPerson = None):
        _m = NaturalPerson
        fields = []
        fields.append((f(_m.person_id), f(_m.stu_id_dbonly)))
        fields.append(f(_m.name))
        fields.append(self._show_by_option(obj, f(_m.show_nickname), f(_m.nickname)))
        fields.append(self._show_by_option(obj, f(_m.show_gender), f(_m.gender)))
        fields.extend([
            f(_m.identity), f(_m.status),
            f(_m.wechat_receive_level),
            f(_m.accept_promote), f(_m.active_score),
        ])
        return fields

    def get_student_fields(self, request, obj: NaturalPerson = None):
        _m = NaturalPerson
        fields = []
        fields.append(f(_m.stu_grade))
        fields.append(f(_m.stu_class))
        fields.append(self._show_by_option(obj, f(_m.show_major), f(_m.stu_major)))
        fields.append(self._show_by_option(obj, f(_m.show_email), f(_m.email)))
        fields.append(self._show_by_option(obj, f(_m.show_tel), f(_m.telephone)))
        fields.append(self._show_by_option(obj, f(_m.show_dorm), f(_m.stu_dorm)))
        fields.append(self._show_by_option(obj, f(_m.show_birthday), f(_m.birthday)))
        return fields

    # 无论如何都不显示的字段
    exclude = [
        f(_m.avatar), f(_m.wallpaper), f(_m.QRcode), f(_m.biography),
        f(_m.unsubscribe_list),
    ]

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            (None, {'fields': self.get_normal_fields(request, obj)}),
            ('学生信息', {'classes': ('collapse',), 
                      'fields': self.get_student_fields(request, obj)}),
        ]
        return fieldsets

    def view_on_site(self, obj: NaturalPerson):
        return obj.get_absolute_url()

    actions = [
        'set_student', 'set_teacher',
        'set_graduate', 'set_ungraduate',
        'all_subscribe', 'all_unsubscribe',
        ]

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
    list_filter = ["otype", "status"]

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
        return obj.get_absolute_url()

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

    @as_action("激活", actions, update=True)
    def set_activate(self, request, queryset):
        queryset.update(status=True)
        return self.message_user(request, '修改成功!')

    @as_action("失效", actions, update=True)
    def set_disabled(self, request, queryset):
        queryset.update(status=False)
        return self.message_user(request, '修改成功!')


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ["person", "org", "pos", "pos_name", "year", "semester", "is_admin"]
    search_fields = ("person__name", "org__oname", 'org__otype__otype_name')
    list_filter = ('year', 'semester','is_admin', 'org__otype', 'pos')
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
            pos.pos = max(0, pos.pos - 1)
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

    @as_action("延长职务年限", actions, atomic=True)
    def refresh(self, request, queryset):
        from boot.config import GLOBAL_CONFIG
        new = []
        for position in queryset:
            position: Position
            if position.year != GLOBAL_CONFIG.acadamic_year and not Position.objects.filter(
                    person=position.person, org=position.org,
                    year=GLOBAL_CONFIG.acadamic_year).exists():
                position.year = GLOBAL_CONFIG.acadamic_year
                position.pk = None
                position.save(force_insert=True)
                new.append([position.pk, position.person.get_display_name()])
        return self.message_user(request, f'修改成功!新增职务：{new}')


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
        "inner", "need_checkin", "valid",
        ErrorFilter,
        'endbefore',
        "publish_time", 'start', 'end',
    )
    date_hierarchy = 'start'

    def participant_diaplay(self, obj):
        return f'{obj.current_participants}/{"无限" if obj.capacity == 10000 else obj.capacity}'
    participant_diaplay.short_description = "报名情况"

    inlines = [ParticipationInline]

    actions = []

    @as_action("更新 报名人数", actions, update=True)
    def refresh_count(self, request, queryset: QuerySet[Activity]):
        for activity in queryset:
            activity.current_participants = sfilter(
                Participation.activity, activity).filter(
                status__in=[
                    Participation.AttendStatus.ATTENDED,
                    Participation.AttendStatus.UNATTENDED,
                    Participation.AttendStatus.APPLYSUCCESS,
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

    def _change_status(self, activity, from_status, to_status):
        from app.activity_utils import changeActivityStatus
        changeActivityStatus(activity.id, from_status, to_status)
        if remove_job(f'activity_{activity.id}_{to_status}'):
            return '修改成功, 并移除了定时任务!'
        else:
            return '修改成功!'

    @as_action("进入 等待中 状态", actions, single=True)
    def to_waiting(self, request, queryset):
        _from, _to = Activity.Status.APPLYING, Activity.Status.WAITING
        msg = self._change_status(queryset[0], _from, _to)
        return self.message_user(request, msg)
    
    @as_action("进入 进行中 状态", actions, single=True)
    def to_processing(self, request, queryset):
        _from, _to = Activity.Status.WAITING, Activity.Status.PROGRESSING
        msg = self._change_status(queryset[0], _from, _to)
        return self.message_user(request, msg)
    
    @as_action("进入 已结束 状态", actions, single=True)
    def to_end(self, request, queryset):
        _from, _to = Activity.Status.PROGRESSING, Activity.Status.END
        msg = self._change_status(queryset[0], _from, _to)
        return self.message_user(request, msg)

    @as_action("取消 定时任务", actions)
    def cancel_scheduler(self, request, queryset):
        success_list = []
        failed_list = []
        CANCEL_STATUSES = [
            'remind',
            Activity.Status.END,
            Activity.Status.PROGRESSING,
            Activity.Status.WAITING,
        ]
        for activity in queryset:
            failed_statuses = []
            for status in CANCEL_STATUSES:
                if not remove_job(f'activity_{activity.id}_{status}'):
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


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    _m = Participation
    _act = _m.activity
    list_display = ['id', f(_act), f(_m.person), f(_m.status)]
    search_fields = ['id', f(_act, 'id'), f(_act, Activity.title),
                     f(_m.person, NaturalPerson.name)]
    list_filter = [
        f(_m.status), f(_act, Activity.category),
        f(_act, Activity.year), f(_act, Activity.semester),
    ]


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
        from app.extern.wechat import publish_notification, WechatApp
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
            from app.extern.wechat import publish_notifications
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
            from app.extern.wechat import WechatApp
            app = WechatApp._PROMOTE
        except Exception as e:
            return self.message_user(request=request,
                                     message=f'导入失败, 原因: {e}',
                                     level='error')
        return self.republish_bulk(request, queryset, app)

    @as_action("重发 所在批次 于 消息窗口")
    def republish_bulk_at_message(self, request, queryset):
        try:
            from app.extern.wechat import WechatApp
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
    actions = []
    ModifyOrganization.get_poster_name.short_description = "申请者"

    @as_action("同意申请", actions, 'change', update = True)
    def approve_requests(self, request, queryset: QuerySet['ModifyOrganization']):
        for application in queryset:
            accept_modifyorg_submit(application)
        self.message_user(request, '操作成功完成！')

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
    _m = CourseRecord
    list_display = [
        _m.get_course_name, f(_m.person),
        f(_m.year), f(_m.semester),
        f(_m.attend_times), f(_m.total_hours),
        f(_m.invalid),
    ]
    search_fields = [
        f(_m.course, Course.name), f(_m.extra_name),
        f(_m.person, NaturalPerson.name),
        f(_m.person, NaturalPerson.person_id, User.username),
    ]
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
    list_filter = [TypeFilter, f(_m.year), f(_m.semester), f(_m.invalid)]

    autocomplete_fields = [f(_m.person), f(_m.course)]

    actions = []

    @as_action('更新来源名称', actions, update=True)
    def update_extra_name(self, request, queryset: QuerySet[CourseRecord]):
        records = queryset.filter(course__isnull=False)
        for record in records.select_related(f(CourseRecord.course)):
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


@admin.register(AcademicTag)
class AcademicTagAdmin(admin.ModelAdmin):
    list_display = ["atype", "tag_content"]
    search_fields =  ("atype", "tag_content")
    list_filter = ["atype"]


class AcademicEntryAdmin(admin.ModelAdmin):
    actions = []

    @as_action("通过审核", actions, 'change', update=True)
    def accept(self, request, queryset):
        queryset.filter(status=AcademicEntry.EntryStatus.WAIT_AUDIT
                        ).update(status=AcademicEntry.EntryStatus.PUBLIC)
        return self.message_user(request, '修改成功!')

    @as_action("取消公开", actions, 'change', update=True)
    def reject(self, request, queryset):
        queryset.filter(status=AcademicEntry.EntryStatus.PUBLIC
                        ).update(status=AcademicEntry.EntryStatus.WAIT_AUDIT)
        return self.message_user(request, '修改成功!')


@admin.register(AcademicTagEntry)
class AcademicTagEntryAdmin(AcademicEntryAdmin):
    list_display = ["person", "status", "tag"]
    search_fields =  ("person__name", "tag__tag_content")
    list_filter = ["tag__atype", "status"]


@admin.register(AcademicTextEntry)
class AcademicTextEntryAdmin(AcademicEntryAdmin):
    list_display = ["person", "status", "atype", "content"]
    search_fields =  ("person__name", "content")
    list_filter = ["atype", "status"]


class PoolItemInline(admin.TabularInline):
    model = PoolItem
    classes = ['collapse']
    ordering = ['-id']
    fields = ['pool', 'prize', 'origin_num', 'consumed_num', 'exchange_limit', 'exchange_price']
    show_change_link = True
PoolItemInline = readonly_inline(PoolItemInline, can_add=True)


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    autocomplete_fields = ['provider']
    inlines = [PoolItemInline]


@admin.register(Pool)
class PoolAdmin(admin.ModelAdmin):
    inlines = [PoolItemInline]
    actions = []

    def _do_draw_lots(self, request, queryset: QuerySet['Pool']):
        '''对queryset中所有未完成抽奖的抽奖奖池进行奖品分配。
        
        这个函数假定queryset已经被select_for_update锁定，所以可以安全地查找“奖池记录”中与该奖池有关的行。
        '''
        lottery_pool_ids = list(queryset.filter(type = Pool.Type.LOTTERY).values_list('id', flat = True))
        for pool_id in lottery_pool_ids:
            pool_title = Pool.objects.get(id = pool_id).title
            if PoolRecord.objects.filter(
                pool__id = pool_id
            ).exclude(
                status = PoolRecord.Status.LOTTERING
            ).exists():
                self.message_user(request, "奖池【" + pool_title + "】在调用前已完成抽奖", 'warning')
                continue
            run_lottery(pool_id)
            self.message_user(request, "奖池【" + pool_title + "】抽奖已完成")

    @as_action('立即抽奖', actions, 'change', update = True)
    def draw_lots(self, request, queryset: QuerySet['Pool']):
        self._do_draw_lots(request, queryset)

    @as_action('立即停止并抽奖', actions, 'change', update = True)
    def stop_and_draw(self, request, queryset: QuerySet['Pool']):
        queryset.update(end = datetime.now())
        self.message_user(request, "已将选中奖池全部停止")
        self._do_draw_lots(request, queryset)


@admin.register(PoolRecord)
class PoolRecordAdmin(admin.ModelAdmin):
    list_display = ['user_display', 'pool', 'status', 'prize', 'time']
    search_fields = ['user__name']
    list_filter = [
        'status', 'prize', 'time',
        ('prize__provider', admin.RelatedOnlyFieldListFilter),
    ]
    readonly_fields = ['time']
    autocomplete_fields = ['user']
    actions = []

    @as_display('用户')
    def user_display(self, obj: PoolRecord):
        return obj.user.name

    def has_manage_permission(self, request: HttpRequest, record: PoolRecord = None) -> bool:
        if not request.user.is_authenticated:
            return False
        if record is not None:
            return record.prize.provider == request.user
        return Prize.objects.filter(provider=request.user).exists()
        # return super().get_queryset(request).filter(prize__provider=request.user).exists()

    def has_module_permission(self, request: HttpRequest) -> bool:
        return super().has_module_permission(request) or self.has_manage_permission(request)

    def has_view_permission(self, request: HttpRequest, obj: PoolRecord = None) -> bool:
        return super().has_view_permission(request, obj) or self.has_manage_permission(request, obj)

    def get_queryset(self, request: HttpRequest):
        qs = super().get_queryset(request)
        if not self.has_change_permission(request) and self.has_manage_permission(request):
            qs = qs.filter(prize__provider=request.user)
        return qs

    @as_action('兑换', actions, ['change', 'manage'], update=True, single=False)  # 修改single为False以允许选择多个记录
    def redeem_prize(self, request, queryset):
        # 检查权限和记录状态，统计可以兑换的记录数
        redeemable_records = []
        for record in queryset:
            if not (self.has_change_permission(request, record) or self.has_manage_permission(request, record)):
                return self.message_user(request, '无权负责一部分选定的礼品兑换!', 'warning')
            if record.status != PoolRecord.Status.UN_REDEEM:
                return self.message_user(request, f'奖品 {record.prize.name} 已被兑换或不可兑换！', 'warning')
            redeemable_records.append(record)

        # 如果没有可兑换的记录，提前返回
        if not redeemable_records:
            return self.message_usesr(request, '没有可兑换的奖品！', 'error')

        # 对可以兑换的记录进行兑换处理
        for record in redeemable_records:
            if record.prize.name.startswith('信用分'):
                User.objects.modify_credit(record.user, 1, '元气值：兑换')
            record.status = PoolRecord.Status.REDEEMED
            record.redeem_time = datetime.now()
            record.save()

        # 返回成功信息
        self.message_user(request, f'成功兑换 {len(redeemable_records)} 个奖品！')

admin.site.register(OrganizationTag)
admin.site.register(Comment)
admin.site.register(CommentPhoto)
admin.site.register(PoolItem)
admin.site.register(ActivitySummary)
