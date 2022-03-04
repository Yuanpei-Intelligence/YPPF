import string
import pypinyin
from datetime import datetime, timedelta

from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django.utils.html import format_html, format_html_join

from django.db import transaction  # 原子化更改数据库
from django.db.models import F

from boottest.admin_utils import *
from Appointment import *
from Appointment.utils import scheduler_func, utils
from Appointment.utils.utils import operation_writer
from Appointment.models import (
    Participant,
    Room,
    Appoint,
    College_Announcement,
    CardCheckInfo,
)


# Register your models here.
# 合并后无需修改
# admin.site.site_title = '元培地下室管理后台'
# admin.site.site_header = '元培地下室 - 管理后台'

@admin.register(College_Announcement)
class College_AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['id', 'announcement', 'show']
    list_editable = ['announcement', 'show']


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    actions_on_top = True
    actions_on_bottom = True
    search_fields = ('Sid__username', 'name', 'pinyin')
    list_display = ('Sid', 'name', 'credit', 'hidden', )
    list_display_links = ('Sid', 'name')
    list_editable = ('credit', )

    class AgreeFilter(admin.SimpleListFilter):
        title = '签署状态'
        parameter_name = 'Agree'
    
        def lookups(self, request, model_admin):
            '''针对字段值设置过滤器的显示效果'''
            return (
                ('true', "已签署"),
                ('false', "未签署"),
            )
        
        def queryset(self, request, queryset):
            '''定义过滤器的过滤动作'''
            if self.value() == 'true':
                return queryset.exclude(agree_time__isnull=True)
            elif self.value() == 'false':
                return queryset.filter(agree_time__isnull=True)
            return queryset

    list_filter = ('credit', 'hidden', AgreeFilter)
    fieldsets = (['基本信息', {
        'fields': (
            'Sid',
            'name',
            'hidden',
        ),
    }], [
        '显示全部', {
            'classes': ('collapse', ),
            'description': '默认信息，不建议修改！',
            'fields': ('credit', 'pinyin', 'agree_time'),
        }
    ])

    @readonly_inline
    class AppointInline(admin.TabularInline):
        # 对外呈现部分
        model = Appoint
        verbose_name = '近两周预约信息'
        verbose_name_plural = verbose_name
        classes = ['collapse']
        # 对内呈现部分（max_num和get_queryset均无法限制呈现个数）
        ordering = ['-Aid']
        fields = [
            'Room', 'Astart', 'Afinish',
            'Astatus', 'Acamera_check_num', 'Acamera_ok_num',
        ]
        show_change_link = True
        # 可申诉的范围只有一周，筛选两周内范围的即可
        def get_queryset(self, request):
            return super().get_queryset(request).filter(
                Astart__gte=datetime.now().date() - timedelta(days=14))


    inlines = [AppointInline]

    actions = []

    @as_action('全院学生信用分恢复一分', actions, 'change', atomic=True)
    def recover(self, request, queryset):
        stu_all = Participant.objects.all()
        stu_all = stu_all.filter(hidden=False)
        stu_all.filter(credit__lt=3).select_for_update().update(
            credit=F('credit') + 1
        )
        return self.message_user(request, '操作成功!')

    @as_action('更新姓名拼音', actions, update=True)
    def renew_pinyin(self, request, queryset):
        for stu in queryset:
            pinyin_list = pypinyin.pinyin(stu.name, style=pypinyin.NORMAL)
            stu.pinyin = ''.join([w[0][0] for w in pinyin_list])
            stu.save()
        return self.message_user(request, '修改学生拼音成功!')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('Rid', 'Rtitle', 'Rmin', 'Rmax', 'Rstart', 'Rfinish',
                    'Rstatus_display', 'RIsAllNight', 'Rpresent', 'Rlatest_time',
                    'RneedAgree',
                    )
    list_display_links = ('Rid', )
    list_editable = ('Rtitle', 'Rmin', 'Rmax', 'Rstart', 'Rfinish', 'RneedAgree')
    search_fields = ('Rid', 'Rtitle')
    list_filter = ('Rstatus', 'RIsAllNight', 'RneedAgree')

    @as_display('预约状态')
    def Rstatus_display(self, obj):
        if obj.Rstatus == Room.Status.PERMITTED:
            color_code = 'green'
        else:
            color_code = 'red'
        return format_html(
            '<span style="color: {};">{}</span>',
            color_code,
            obj.get_Rstatus_display(),
        )


@admin.register(Appoint)
class AppointAdmin(admin.ModelAdmin):
    actions_on_top = True
    actions_on_bottom = True
    LETTERS = set(string.digits + string.ascii_letters + string.punctuation)
    search_fields = ('Aid', 'Room__Rtitle',
                     'major_student__name', 'Room__Rid', "students__name",
                     'major_student__pinyin', # 仅发起者缩写，方便搜索者区分发起者和参与者
                     )
    list_display = (
        'Aid',
        'Room',
        'Astart',
        # 'Afinish',
        # 'Atime',  # 'Ausage',
        'major_student_display',
        'Participants',
        # 'total_display',
        'usage_display',
        'check_display',
        'Astatus_display',
    )
    list_display_links = ('Aid', 'Room')
    list_per_page = 25
    list_editable = (
        'Astart',
        # 'Afinish',
    )  # 'Ausage'
    date_hierarchy = 'Astart'
    autocomplete_fields = ['major_student']
    filter_horizontal = ['students']
    readonly_fields = ('Atime', )

    class ActivateFilter(admin.SimpleListFilter):
        title = '有效状态' # 过滤标题显示为"以 有效状态"
        parameter_name = 'Activate' # 过滤器使用的过滤字段
    
        def lookups(self, request, model_admin):
            '''针对字段值设置过滤器的显示效果'''
            return (
                ('true', "有效"),
                ('false', "无效"),
            )
        
        def queryset(self, request, queryset):
            '''定义过滤器的过滤动作'''
            if self.value() == 'true':
                return queryset.exclude(Astatus=Appoint.Status.CANCELED)
            elif self.value() == 'false':
                return queryset.filter(Astatus=Appoint.Status.CANCELED)
            return queryset

    list_filter = ('Astart', 'Atime', 'Astatus', ActivateFilter, 'Atemp_flag')

    @as_display('参与人')
    def Participants(self, obj):
        students = [(obj.major_student.name, )]
        students += [(stu.name, ) for stu in obj.students.all()
                                    if stu != obj.major_student]
        return format_html_join('\n', '<li>{}</li>', students)

    @as_display('用途')
    def usage_display(self, obj):
        batch = 6
        half_len = 18
        usage = obj.Ausage
        if len([c for c in usage if c in AppointAdmin.LETTERS]) > .6 * len(usage):
            batch *= 2
            half_len *= 2
        if len(obj.Ausage) < half_len * 2:
            usage = obj.Ausage
        else:
            usage = obj.Ausage[:half_len] + '...' + obj.Ausage[3-half_len:]
        usage = '<br/>'.join([usage[i:i+batch] for i in range(0, len(usage), batch)])
        return mark_safe(usage)

    @as_display('通过率')
    def check_display(self, obj):
        return f'{obj.Acamera_ok_num}/{obj.Acamera_check_num}'

    @as_display('总人数')
    def total_display(self, obj):
        return obj.Anon_yp_num + obj.Ayp_num

    @as_display('发起人')
    def major_student_display(self, obj):
        return obj.major_student.name

    @as_display('预约状态')
    def Astatus_display(self, obj):
        status2color = {
            Appoint.Status.CANCELED: 'grey',
            Appoint.Status.APPOINTED: 'black',
            Appoint.Status.PROCESSING: 'purple',
            Appoint.Status.WAITING: 'blue',
            Appoint.Status.CONFIRMED: 'green',
            Appoint.Status.VIOLATED: 'red',
            Appoint.Status.JUDGED: 'yellowgreen',
        }
        color_code = status2color[obj.Astatus]
        status = obj.get_status()
        # if obj.Atemp_flag == Appoint.Bool_flag.Yes:
        #     status = '临时:' + status
        return format_html(
            '<span style="color: {};">{}</span>',
            color_code,
            status,
        )

    actions = []

    @as_action('所选条目 通过', actions, 'change')
    def confirm(self, request, queryset):  # 确认通过
        some_invalid = 0
        have_success = 0
        try:
            with transaction.atomic():
                for appoint in queryset:
                    if appoint.Astatus == Appoint.Status.WAITING:
                        appoint.Astatus = Appoint.Status.CONFIRMED
                        appoint.save()
                        have_success = 1
                        # send wechat message
                        # TODO: major_sid
                        scheduler_func.set_appoint_wechat(
                            appoint, 'confirm_admin_w2c', appoint.get_status(),
                            students_id=[appoint.major_student.Sid_id], admin=True,
                            id=f'{appoint.Aid}_confirm_admin_wechat')
                        operation_writer(SYSTEM_LOG, str(appoint.Aid)+"号预约被管理员从WAITING改为CONFIRMED" +
                                 "发起人："+str(appoint.major_student), "admin.confirm", "OK")
                    elif appoint.Astatus == Appoint.Status.VIOLATED:
                        appoint.Astatus = Appoint.Status.JUDGED
                        # for stu in appoint.students.all():
                        if appoint.major_student.credit < 3:
                            appoint.major_student.credit += 1
                            appoint.major_student.save()
                        appoint.save()
                        have_success = 1
                        # send wechat message
                        # TODO: major_sid
                        scheduler_func.set_appoint_wechat(
                            appoint, 'confirm_admin_v2j', appoint.get_status(),
                            students_id=[appoint.major_student.Sid_id], admin=True,
                            id=f'{appoint.Aid}_confirm_admin_wechat')
                        operation_writer(SYSTEM_LOG, str(appoint.Aid)+"号预约被管理员从VIOLATED改为JUDGED" +
                                 "发起人："+str(appoint.major_student), "admin.confirm", "OK")

                    else:  # 不允许更改
                        some_invalid = 1

        except:
            return self.message_user(request=request,
                                     message='操作失败!请与开发者联系!',
                                     level=messages.WARNING)
        if not some_invalid:
            return self.message_user(request, "更改状态成功!")
        else:
            if have_success:
                return self.message_user(request=request,
                                         message='部分修改成功!但遭遇状态不为等待、违约的预约，这部分预约不允许更改!',
                                         level=messages.WARNING)
            else:
                return self.message_user(request=request,
                                         message='修改失败!不允许修改状态不为等待、违约的预约!',
                                         level=messages.WARNING)


    @as_action('所选条目 违约', actions, 'change')
    def violate(self, request, queryset):  # 确认违约
        try:
            for appoint in queryset:
                assert not (
                    appoint.Astatus == Appoint.Status.VIOLATED
                    and appoint.Areason == Appoint.Reason.R_ELSE
                )
                ori_status = appoint.get_status()
                # if appoint.Astatus == Appoint.Status.WAITING:
                # 已违规时不扣除信用分，仅提示用户
                if appoint.Astatus != Appoint.Status.VIOLATED:
                    appoint.Astatus = Appoint.Status.VIOLATED
                    appoint.major_student.credit -= 1  # 只扣除发起人
                    appoint.major_student.save()
                appoint.Areason = Appoint.Reason.R_ELSE
                appoint.save()

                # send wechat message
                # TODO: major_sid
                scheduler_func.set_appoint_wechat(
                    appoint, 'violate_admin', f'原状态：{ori_status}',
                    students_id=[appoint.major_student.Sid_id], admin=True,
                    id=f'{appoint.Aid}_violate_admin_wechat')
                operation_writer(SYSTEM_LOG, str(
                    appoint.Aid)+"号预约被管理员设为违约"+"发起人："+str(appoint.major_student), "admin.violate", "OK")
        except:
            return self.message_user(request=request,
                                     message='操作失败!只允许对未审核的条目操作!',
                                     level=messages.WARNING)

        return self.message_user(request, "设为违约成功!")

    
    @as_action('更新定时任务', actions, ['add', 'change'])
    def refresh_scheduler(self, request, queryset):
        '''
        假设的情况是后台修改了开始和结束时间后，需要重置定时任务
        因此，旧的定时任务可能处于任何完成状态
        '''
        for appoint in queryset:
            try:
                aid = appoint.Aid
                start = appoint.Astart
                finish = appoint.Afinish
                if start > finish:
                    return self.message_user(request=request,
                                            message=f'操作失败,预约{aid}开始和结束时间冲突!请勿篡改数据!',
                                            level=messages.WARNING)
                scheduler_func.cancel_scheduler(aid)    # 注销原有定时任务 无异常
                scheduler_func.set_scheduler(appoint)   # 开始时进入进行中 结束后判定
                if datetime.now() < start:              # 如果未开始，修改开始提醒
                    scheduler_func.set_start_wechat(appoint, notify_new=False)
            except Exception as e:
                operation_writer(SYSTEM_LOG,
                                 "出现更新定时任务失败的问题: " + str(e),
                                 "admin.longterm",
                                 "Error")
                return self.message_user(request, str(e), messages.WARNING)
        return self.message_user(request, '定时任务更新成功!')
    

    def longterm_wk(self, request, queryset, times, interval_week=1):
        for appoint in queryset:
            try:
                with transaction.atomic():
                    stuid_list = [stu.Sid_id for stu in appoint.students.all()]
                    for i in range(1, times + 1):
                        # 调用函数完成预约
                        feedback = scheduler_func.addAppoint({
                            'Rid':
                            appoint.Room.Rid,
                            'students':
                            stuid_list,
                            'non_yp_num':
                            appoint.Anon_yp_num,
                            'Astart':
                            appoint.Astart + i * timedelta(days=7 * interval_week),
                            'Afinish':
                            appoint.Afinish + i * timedelta(days=7 * interval_week),
                            'Sid':
                            # TODO: major_sid
                            appoint.major_student.Sid_id,
                            'Ausage':
                            appoint.Ausage,
                            'announcement':
                            appoint.Aannouncement,
                            'new_require':  # 长线预约,不需要每一个都添加信息, 直接统一添加
                            0
                        })
                        if feedback.status_code != 200:  # 成功预约
                            import json
                            warning = json.loads(feedback.content)['statusInfo']['message']
                            print(warning)
                            raise Exception(warning)
            except Exception as e:
                operation_writer(SYSTEM_LOG, "学生" + str(appoint.major_student) +
                                 "出现添加长线化预约失败的问题:"+str(e), "admin.longterm", "Problem")
                return self.message_user(request=request,
                                         message=str(e),
                                         level=messages.WARNING)

            # 到这里, 长线化预约发起成功
            scheduler_func.set_longterm_wechat(
                appoint, infos=f'新增了{times}周同时段预约', admin=True)
            # TODO: major_sid
            operation_writer(appoint.major_student.Sid_id, "发起"+str(times) +
                             "周的长线化预约, 原始预约号"+str(appoint.Aid), "admin.longterm", "OK")
        return self.message_user(request, '长线化成功!')


    def new_longterm_wk(self, request, queryset, times, interval_week=1):
        new_appoints = {}
        for appoint in queryset:
            try:
                conflict_week, appoints = (
                    scheduler_func.add_longterm_appoint(
                        appoint, times, interval_week, admin=True))
                if conflict_week is not None:
                    return self.message_user(
                        request,
                        f'第{conflict_week}周存在冲突的预约: {appoints[0].Aid}!',
                        level=messages.WARNING)
                new_appoints[appoint.pk] = list(appoints.values_list('pk', flat=True))
            except Exception as e:
                return self.message_user(request, f'长线化失败!', messages.WARNING)
        new_infos = []
        if len(new_appoints) == 1:
            for appoint, new_appoint_ids in new_appoints.items():
                new_infos.append(f'{new_appoint_ids}'[1:-1])
        else:
            for appoint, new_appoint_ids in new_appoints.items():
                new_infos.append(f'{appoint}->{new_appoint_ids}')
        return self.message_user(request, f'长线化成功!生成预约{";".join(new_appoints)}')


    @as_action('增加一周本预约', actions, 'add', single=True)
    def longterm1(self, request, queryset):
        return self.longterm_wk(request, queryset, 1)

    @as_action('增加两周本预约', actions, 'add', single=True)
    def longterm2(self, request, queryset):
        return self.longterm_wk(request, queryset, 2)

    @as_action('增加四周本预约', actions, 'add', single=True)
    def longterm4(self, request, queryset):
        return self.longterm_wk(request, queryset, 4)

    @as_action('增加八周本预约', actions, 'add', single=True)
    def longterm8(self, request, queryset):
        return self.longterm_wk(request, queryset, 8)

    @as_action('按单双周 增加一次本预约', actions, 'add', single=True)
    def longterm1_2(self, request, queryset):
        return self.longterm_wk(request, queryset, 1, 2)

    @as_action('按单双周 增加两次本预约', actions, 'add', single=True)
    def longterm2_2(self, request, queryset):
        return self.longterm_wk(request, queryset, 2, 2)

    @as_action('按单双周 增加四次本预约', actions, 'add', single=True)
    def longterm4_2(self, request, queryset):
        return self.longterm_wk(request, queryset, 4, 2)


@admin.register(CardCheckInfo)
class CardCheckInfoAdmin(admin.ModelAdmin):
    list_display = ('id', 'Cardroom', 'student_display', 'Cardtime',
                    'CardStatus', 'ShouldOpenStatus', 'Message')  # 'is_delete'
    search_fields = ('Cardroom__Rtitle',
                     'Cardstudent__name', 'Cardroom__Rid', "id")
    list_filter = ('CardStatus', 'ShouldOpenStatus')
    
    @as_display('刷卡者', except_value='-')
    def student_display(self, obj):
        return obj.Cardstudent.name
