import string
import openpyxl
import pypinyin
from datetime import datetime, timedelta

from django import forms
from django.http import HttpResponse
from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django.shortcuts import render, redirect
from django.utils.html import format_html, format_html_join
from django.db.models import QuerySet
from django.db import transaction
from django.urls import path, reverse

from utils.admin_utils import *
from Appointment import jobs
from Appointment.appoint.jobs import set_scheduler, cancel_scheduler
from Appointment.extern.wechat import MessageType, notify_appoint
from Appointment.extern.jobs import set_appoint_reminder
from Appointment.utils.log import logger
from Appointment.models import *


def _appointor(appoint: Appoint) -> str:
    '''可追溯引用的str调用'''
    return appoint.major_student.__str__()


class ExcelImportForm(forms.Form):
    """
    用于上传Excel的Form，只包含一个上传文件的字段
    """
    excel_file = forms.FileField(
        label=("请选择要上传的Excel文件"),
        required=True
    )
@admin.register(College_Announcement)
class College_AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['id', 'announcement', 'show']
    list_editable = ['announcement', 'show']


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    actions_on_top = True
    actions_on_bottom = True
    search_fields = ('Sid__username', 'Sid__name', 'Sid__pinyin', 'Sid__acronym')
    list_display = ('Sid_id', 'name', 'credit', 'longterm', 'hidden')
    list_display_links = ('Sid_id', 'name')

    list_filter = ('Sid__credit', 'longterm', 'hidden')

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

    @as_action('全院学生信用分恢复一分', actions, atomic=True)
    def recover(self, request, queryset):
        stu_all = Participant.objects.all()
        stu_all = stu_all.filter(hidden=False)
        stu_all = User.objects.filter(id__in=stu_all.values_list('Sid__id'))
        User.objects.bulk_recover_credit(stu_all, 1, '全体学生恢复')
        return self.message_user(request, '操作成功!')

    @as_action('赋予长期预约权限', actions, 'change', update=True)
    def add_longterm_perm(self, request, queryset: QuerySet[Participant]):
        queryset.update(longterm=True)
        return self.message_user(request, '操作成功!')

    @as_action('收回长期预约权限', actions, 'change', update=True)
    def remove_longterm_perm(self, request, queryset: QuerySet[Participant]):
        queryset.update(longterm=False)
        return self.message_user(request, '操作成功!')

    @as_action('设为不可见', actions, 'change', update=True)
    def set_hidden(self, request, queryset: QuerySet[Participant]):
        queryset.update(hidden=True)
        return self.message_user(request, '操作成功!')

    @as_action('设为可见', actions, 'change', update=True)
    def remove_hidden(self, request, queryset: QuerySet[Participant]):
        queryset.update(hidden=False)
        return self.message_user(request, '操作成功!')


@admin.register(RoomClass)
class RoomClassAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'sort_idx',)
    ordering = ('sort_idx',)
    # For many-to-many fields
    filter_horizontal = ('rooms',)

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


@admin.register(EntranceGuard)
class EntranceGuardAdmin(admin.ModelAdmin):
    pass


@admin.register(Appoint)
class AppointAdmin(admin.ModelAdmin):
    actions_on_top = True
    actions_on_bottom = True
    LETTERS = set(string.digits + string.ascii_letters + string.punctuation)
    search_fields = ('Room__Rtitle', 'Room__Rid',
                     'major_student__name', "students__name",
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
        'Atype',
    )
    list_select_related = ('Room', 'major_student__Sid')
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

    list_filter = ('Astart', 'Atime', 'Astatus', ActivateFilter, 'Atype')

    def get_search_results(self, request, queryset, search_term: str):
        if not search_term:
            return queryset, False
        try:
            search_term = int(search_term)
            return queryset.filter(pk=search_term), False
        except:
            pass
        if ' ' not in search_term:
            # 判断时需要增加exists，否则会报错，似乎是QuerySet的缓存问题？
            if str.isascii(search_term) and str.isalpha(search_term):
                pinyin_result = queryset.filter(major_student__pinyin__icontains=search_term)
                if pinyin_result.exists():
                    return pinyin_result, False
            elif str.isascii(search_term) and str.isalnum(search_term):
                room_result = queryset.filter(Room__Rid__iexact=search_term)
                if room_result.exists():
                    return room_result, False
            else:
                room_result = queryset.filter(Room__Rtitle__icontains=search_term)
                if room_result.exists():
                    return room_result, False
        return super().get_search_results(request, queryset, search_term)

    @as_display('参与人')
    def Participants(self, obj: Appoint):
        names = [(obj.major_student.name, )]
        participants = obj.students.exclude(pk=obj.get_major_id())
        names += list(participants.values_list('Sid__name', flat=False))
        return format_html_join('\n', '<li>{}</li>', names)

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
        return format_html(
            '<span style="color: {};">{}</span>',
            color_code,
            status,
        )

    actions = []

    def _waiting2confirm(self, appoint: Appoint):
        appoint.Astatus = Appoint.Status.CONFIRMED
        appoint.save()
        notify_appoint(appoint, MessageType.PRE_CONFIRMED, appoint.get_status(),
                       students_id=[appoint.get_major_id()], admin=True)
        logger.info(f"{appoint.Aid}号预约被管理员通过，发起人：{_appointor(appoint)}")


    def _violated2judged(self, appoint: Appoint):
        appoint.Astatus = Appoint.Status.JUDGED
        appoint.save()
        User.objects.modify_credit(appoint.get_major_id(), 1, '申诉')
        notify_appoint(appoint, MessageType.APPEAL_APPROVED, appoint.get_status(),
                       students_id=[appoint.get_major_id()], admin=True)
        logger.info(f"{appoint.Aid}号预约被管理员通过，发起人：{_appointor(appoint)}")


    @as_action('所选条目 通过', actions, 'change', update=True)
    def confirm(self, request, queryset: QuerySet[Appoint]):  # 确认通过
        invalid = []
        for appoint in queryset:
            match appoint.Astatus:
                case Appoint.Status.WAITING:
                    self._waiting2confirm(appoint)
                case Appoint.Status.VIOLATED:
                    self._violated2judged(appoint)
                case _:
                    invalid.append(appoint)
        if not invalid:
            return self.message_user(request, '更改状态成功!')
        if len(invalid) == len(queryset):
            return self.message_user(request, '只可通过等待、违约中的预约!', messages.WARNING)
        message = f'部分成功!但{invalid}状态不为等待、违约，不允许更改!'
        return self.message_user(request, message, messages.WARNING)


    @as_action('所选条目 违约', actions, 'change', update=True)
    def violate(self, request, queryset: QuerySet[Appoint]):  # 确认违约
        for appoint in queryset:
            if (appoint.Astatus == Appoint.Status.VIOLATED
                and appoint.Areason == Appoint.Reason.R_ELSE):
                return self.message_user(
                    request, '操作失败!只允许对未审核的条目操作!', messages.WARNING)
            ori_status = appoint.get_status()
            if appoint.Astatus != Appoint.Status.VIOLATED:
                appoint.Astatus = Appoint.Status.VIOLATED
                User.objects.modify_credit(appoint.get_major_id(), -1, '后台')
            appoint.Areason = Appoint.Reason.R_ELSE
            appoint.save()

            # send wechat message
            notify_appoint(
                appoint, MessageType.REVIEWD_VIOLATE, f'原状态：{ori_status}',
                students_id=[appoint.get_major_id()], admin=True)
            logger.info(f"{appoint.Aid}号预约被管理员设为违约，发起人：{_appointor(appoint)}")

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
                    return self.message_user(request, 
                        f'操作失败,预约{aid}开始和结束时间冲突!请勿篡改数据!', messages.WARNING)
                cancel_scheduler(aid)    # 注销原有定时任务 无异常
                set_scheduler(appoint)   # 开始时进入进行中 结束后判定
                set_appoint_reminder(appoint)
            except Exception as e:
                logger.error(f"定时任务失败更新: {e}")
                return self.message_user(request, str(e), messages.WARNING)
        return self.message_user(request, '定时任务更新成功!')


    def longterm_wk(self, request, queryset, times, interval_week=1):
        new_appoints = {}
        for appoint in queryset:
            try:
                conflict_week, appoints = (
                    jobs.add_longterm_appoint(
                        appoint.pk, times, interval_week, admin=True))
                if conflict_week is not None:
                    return self.message_user(
                        request,
                        f'第{conflict_week}周存在冲突的预约: {appoints[0].Aid}!',
                        level=messages.WARNING)
                longterm_info = jobs.get_longterm_display(times, interval_week)
                notify_appoint(appoint, MessageType.LONGTERM_CREATED,
                               f'新增了{longterm_info}同时段预约', admin=True)
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


    # @as_action('增加一周本预约', actions, 'add', single=True)
    def longterm1(self, request, queryset):
        return self.longterm_wk(request, queryset, 1)

    # @as_action('增加两周本预约', actions, 'add', single=True)
    def longterm2(self, request, queryset):
        return self.longterm_wk(request, queryset, 2)

    # @as_action('增加四周本预约', actions, 'add', single=True)
    def longterm4(self, request, queryset):
        return self.longterm_wk(request, queryset, 4)

    # @as_action('增加八周本预约', actions, 'add', single=True)
    def longterm8(self, request, queryset):
        return self.longterm_wk(request, queryset, 8)

    # @as_action('按单双周 增加一次本预约', actions, 'add', single=True)
    def longterm1_2(self, request, queryset):
        return self.longterm_wk(request, queryset, 1, 2)

    # @as_action('按单双周 增加两次本预约', actions, 'add', single=True)
    def longterm2_2(self, request, queryset):
        return self.longterm_wk(request, queryset, 2, 2)

    # @as_action('按单双周 增加四次本预约', actions, 'add', single=True)
    def longterm4_2(self, request, queryset):
        return self.longterm_wk(request, queryset, 4, 2)

    # 2024.12.28 以下为批量导入逻辑

    change_list_template = "admin/appointment_changelist.html"

    def get_urls(self):
        """
        重写get_urls，为Admin添加一个新的url映射(import_excel)。
        """
        urls = super().get_urls()
        my_urls = [
            path("import-excel/", self.admin_site.admin_view(self.import_excel_view),
                 name="appointment_import_excel"),
        ]
        return my_urls + urls

    def import_excel_view(self, request):
        """
        用于上传并处理Excel文件的自定义视图。
        """
        context = dict(
            self.admin_site.each_context(request),
            opts=self.model._meta,
        )

        if request.method == "POST":
            form = ExcelImportForm(request.POST, request.FILES)
            if form.is_valid():
                excel_file = request.FILES["excel_file"]
                imported_count = 0
                skipped_rows = []

                try:
                    with transaction.atomic():
                        wb = openpyxl.load_workbook(excel_file)
                        sheet = wb.active

                        for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                            if row_idx == 1:  # 跳过标题行
                                continue

                            try:
                                # 根据测试数据调整列索引
                                # 姓名	部门	职工号或学号	资源名称	创建时间	预约时间	预约人数	状态	预约理由
                                # 0      1      2           3          4          5           6          7      8
                                if len(row) < 9:
                                    skipped_rows.append(
                                        f"第 {row_idx} 行数据列数不足，已跳过。")
                                    continue

                                name = str(row[0]).strip() if row[0] else ""
                                # department = str(row[1]).strip() # 部门，暂未使用
                                sid = str(row[2]).strip() if row[2] else ""
                                room_name = str(
                                    row[3]).strip() if row[3] else ""
                                create_time_str = str(
                                    row[4]).strip() if row[4] else ""
                                appoint_times_str = str(
                                    row[5]).strip() if row[5] else ""
                                person_num_str = str(
                                    row[6]).strip() if row[6] else ""
                                # status_str = str(row[7]).strip() # 状态，暂未使用，将直接创建为“已预约”
                                usage = str(row[8]).strip() if row[8] else ""

                                # 基本校验：学号、房间名、预约时间不能为空
                                if not all([sid, room_name, appoint_times_str, create_time_str]):
                                    skipped_rows.append(
                                        f"第 {row_idx} 行关键信息缺失 (学号, 房间名, 创建时间或预约时间)，已跳过。")
                                    continue

                                # 1. 获取或创建主要参与者 (Major Student)
                                try:
                                    major_participant_user, created = User.objects.get_or_create(
                                        username=sid,
                                        defaults={
                                            'name': name,
                                            'pinyin': "".join(pypinyin.lazy_pinyin(name, style=pypinyin.Style.NORMAL)),
                                            'acronym': "".join([i[0] for i in pypinyin.lazy_pinyin(name, style=pypinyin.Style.NORMAL)]).lower()
                                        }
                                    )
                                    major_participant, _ = Participant.objects.get_or_create(
                                        Sid=major_participant_user,
                                        defaults={'name': name}
                                    )
                                except Exception as e:
                                    skipped_rows.append(
                                        f"第 {row_idx} 行处理发起人 '{name}({sid})' 失败: {e}，已跳过。")
                                    continue

                                # 2. 获取房间
                                try:
                                    room = Room.objects.get(Rtitle=room_name)
                                except Room.DoesNotExist:
                                    skipped_rows.append(
                                        f"第 {row_idx} 行房间 '{room_name}' 不存在，已跳过。")
                                    continue
                                except Room.MultipleObjectsReturned:
                                    # 如果房间名不唯一，可以考虑更复杂的逻辑或报错
                                    room = Room.objects.filter(
                                        Rtitle=room_name).first()
                                    if not room:  # Should not happen if MultipleObjectsReturned
                                        skipped_rows.append(
                                            f"第 {row_idx} 行房间 '{room_name}' 查找异常，已跳过。")
                                        continue
                                    messages.warning(
                                        request, f"第 {row_idx} 行房间 '{room_name}' 存在多个匹配项，已选择第一个。")

                                # 3. 解析创建时间 (Atime)
                                try:
                                    apply_time = datetime.strptime(
                                        create_time_str, '%Y-%m-%d %H:%M:%S')
                                except ValueError:
                                    try:  # 尝试另一种常见格式
                                        apply_time = datetime.fromisoformat(
                                            create_time_str)
                                    except ValueError:
                                        skipped_rows.append(
                                            f"第 {row_idx} 行创建时间 '{create_time_str}' 格式错误，应为 'YYYY-MM-DD HH:MM:SS'，已跳过。")
                                        continue

                                # 4. 解析预约人数
                                try:
                                    person_num = int(
                                        person_num_str) if person_num_str else 1
                                except ValueError:
                                    skipped_rows.append(
                                        f"第 {row_idx} 行预约人数 '{person_num_str}' 非数字，已跳过。")
                                    continue

                                # 5. 解析并创建多个预约时段
                                # 示例: "2025-07-03 20:00-21:00, 2025-07-03 19:00-20:00"
                                individual_appoint_slots = [
                                    slot.strip() for slot in appoint_times_str.split(',')]
                                if not individual_appoint_slots or not any(individual_appoint_slots):
                                    skipped_rows.append(
                                        f"第 {row_idx} 行预约时间格式不正确或为空，已跳过。")
                                    continue

                                for slot_idx, time_slot_str in enumerate(individual_appoint_slots):
                                    if not time_slot_str:
                                        continue
                                    try:
                                        # 假定格式 "YYYY-MM-DD HH:MM-HH:MM"
                                        date_str, time_range_str = time_slot_str.split(
                                            ' ', 1)
                                        start_time_str, finish_time_str = time_range_str.split(
                                            '-')

                                        astart_dt_str = f"{date_str} {start_time_str.strip()}"
                                        afinish_dt_str = f"{date_str} {finish_time_str.strip()}"

                                        astart = datetime.strptime(
                                            astart_dt_str, '%Y-%m-%d %H:%M')
                                        afinish = datetime.strptime(
                                            afinish_dt_str, '%Y-%m-%d %H:%M')

                                        if astart >= afinish:
                                            skipped_rows.append(
                                                f"第 {row_idx} 行, 时段 {slot_idx+1} ('{time_slot_str}') 结束时间早于或等于开始时间，已跳过。")
                                            continue

                                        # 创建 Appoint 对象
                                        appoint = Appoint(
                                            Astart=astart,
                                            Afinish=afinish,
                                            Ausage=usage if usage else "导入预约",
                                            Room=room,
                                            major_student=major_participant,
                                            Astatus=Appoint.Status.APPOINTED,  # 默认为已预约
                                            Ayp_num=person_num,
                                            Anon_yp_num=0,  # 假设导入的都是院内，可根据需要修改
                                            Aneed_num=person_num,  # 检查人数要求，暂设为总人数
                                            # Atime 会通过 auto_now_add 设置，如果希望使用Excel中的创建时间，需修改模型字段或手动设置
                                        )
                                        # 如果希望使用Excel的创建时间，且Atime没有auto_now_add=True
                                        # appoint.Atime = apply_time # 取消注释并确保模型字段允许

                                        appoint.save()  # 保存Appoint对象以获得Aid

                                        # 添加参与者 (包括主要参与者)
                                        appoint.students.add(major_participant)
                                        # 如果Excel中有其他参与者信息，也需要在这里处理并添加

                                        # 设置 Atime (如果不由auto_now_add控制)
                                        # 如果要强制设定 Atime 为 Excel 中的时间，可以这样做：
                                        if hasattr(Appoint, 'Atime') and not Appoint._meta.get_field('Atime').auto_now_add:
                                            appoint.Atime = apply_time
                                            appoint.save(
                                                update_fields=['Atime'])
                                        elif Appoint._meta.get_field('Atime').auto_now_add and apply_time:
                                            # 如果是 auto_now_add, 但仍想记录Excel中的申请时间，可以新增一个字段
                                            # 或者，如果只是想在导入时覆盖，可以考虑临时移除auto_now_add，
                                            # 但更安全的做法是，如果创建时间很重要，则模型不应设为auto_now_add
                                            # 这里选择更新，虽然auto_now_add通常在create时生效
                                            Appoint.objects.filter(
                                                pk=appoint.pk).update(Atime=apply_time)

                                        # 设置定时任务等 (如果需要)
                                        # set_scheduler(appoint)
                                        # set_appoint_reminder(appoint)
                                        # logger.info(f"Imported appointment {appoint.Aid} for {major_participant.name} in room {room.Rtitle}")

                                        imported_count += 1

                                    except ValueError as ve:
                                        skipped_rows.append(
                                            f"第 {row_idx} 行, 时段 {slot_idx+1} ('{time_slot_str}') 时间格式错误: {ve}，已跳过。")
                                        continue
                                    except Exception as e_slot:
                                        skipped_rows.append(
                                            f"第 {row_idx} 行, 时段 {slot_idx+1} ('{time_slot_str}') 创建预约失败: {e_slot}，已跳过。")
                                        continue

                            except Exception as e_row:
                                skipped_rows.append(
                                    f"处理第 {row_idx} 行数据时发生意外错误: {e_row}，已跳过。")
                                continue

                    if imported_count > 0:
                        messages.success(
                            request, f"成功导入 {imported_count} 条预约记录。")
                    else:
                        messages.warning(request, "没有成功导入任何预约记录。")

                    if skipped_rows:
                        messages.warning(request, mark_safe(
                            "以下行导入失败或被跳过：<br>" + "<br>".join(skipped_rows)))

                except Exception as e:
                    messages.error(request, f"导入过程中发生严重错误：{e}")
                    # 如果在事务中发生错误，Django会自动回滚

            else:  # form is not valid
                messages.error(request, "上传的文件无效或表单错误。")

        else:  # GET request
            form = ExcelImportForm()

        context["form"] = form
        return render(request, "admin/appointment_import_excel.html", context)


@admin.register(CardCheckInfo)
class CardCheckInfoAdmin(admin.ModelAdmin):
    list_display = ('id', 'Cardroom', 'student_display', 'Cardtime',
                    'CardStatus', 'Message')
    list_select_related = ('Cardroom', 'Cardstudent__Sid')
    search_fields = ('Cardroom__Rtitle',
                     'Cardstudent__name', 'Cardroom__Rid', "id")
    list_filter = [
        'Cardtime', 'CardStatus',
        ('Cardroom', admin.EmptyFieldListFilter),
    ]
    
    @as_display('刷卡者', except_value='-')
    def student_display(self, obj):
        return obj.Cardstudent.name


@admin.register(LongTermAppoint)
class LongTermAppointAdmin(admin.ModelAdmin):
    list_display = ['id', 'applicant', 'times', 'interval', 'status']
    list_select_related = ['applicant__Sid']
    list_filter = ['status', 'times', 'interval']
    raw_id_fields = ['appoint']

    def view_on_site(self, obj: LongTermAppoint):
        return f'/underground/review?Lid={obj.pk}'
