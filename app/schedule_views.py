"""日程表页面：整合书院课时间、报名活动时间与地下室预约，并支持手动日程/待办。"""
import re
import uuid
from datetime import date, datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from app.models import (
    AcademicCourse,
    Activity,
    Course,
    CourseParticipant,
    NaturalPerson,
    Participation,
    UserSchedule,
)
from app.pku_course_parser import expand_lesson_to_events, parse_pku_course_html
from app.view.base import ProfileTemplateView
from Appointment.utils.web_func import get_appoints
from utils.global_messages import (
    get_request_message,
    message_url,
    succeed,
    transfer_message_context,
    wrong,
)

__all__ = [
    'mySchedule',
    'importCourseTable',
    'addScheduleItem',
    'editScheduleItem',
    'deleteScheduleItem',
    'toggleTodo',
    'manageSchedule',
]

# 上传页允许的最大文件体积（门户课表 HTML 通常 < 200KB）
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
# 单双周字符 -> AcademicCourse.Parity 整数
_PARITY_MAP = {'ALL': AcademicCourse.Parity.ALL,
               'ODD': AcademicCourse.Parity.ODD,
               'EVEN': AcademicCourse.Parity.EVEN}
# 手动日程颜色格式（渲染进日历事件，需严格校验）
_HEX_COLOR_RE = re.compile(r'#[0-9A-Fa-f]{6}')
# AcademicCourse.term 列宽，超长会在 MySQL 严格模式下报错
_TERM_MAX_LENGTH = AcademicCourse._meta.get_field('term').max_length


# ---------------------------------------------------------------------------
# 手动日程 / 待办：表单与重复实体化
# ---------------------------------------------------------------------------
class UserScheduleForm(forms.ModelForm):
    """手动日程/待办的创建与编辑表单（服务端校验）。"""

    class Meta:
        model = UserSchedule
        fields = [
            'title', 'category', 'date', 'start_time', 'end_time',
            'location', 'note', 'color', 'repeat', 'repeat_end',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '标题'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={
                'type': 'date', 'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={
                'type': 'time', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={
                'type': 'time', 'class': 'form-control'}),
            'location': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '选填'}),
            'note': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '选填'}),
            'color': forms.TextInput(attrs={
                'type': 'color', 'class': 'form-control'}),
            'repeat': forms.Select(attrs={'class': 'form-control'}),
            'repeat_end': forms.DateInput(attrs={
                'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # color/repeat 在模型上有默认值，但未声明 blank=True，ModelForm 因此判定
        # 为必填。「当日待办」快速表单只提交 title/category/date，需允许省略并在
        # 服务端回落到模型默认值，否则该表单永远校验失败。
        for name in ('color', 'repeat'):
            self.fields[name].required = False

    def clean_color(self):
        color = (self.cleaned_data.get('color') or '').strip()
        if not color:
            return UserSchedule._meta.get_field('color').get_default()
        # 颜色会被渲染进日历事件，限定为标准 6 位十六进制，避免注入非法内容
        if not _HEX_COLOR_RE.fullmatch(color):
            raise ValidationError('颜色格式应为 #RRGGBB。')
        return color

    def clean_repeat(self):
        repeat = self.cleaned_data.get('repeat')
        if repeat in (None, ''):
            return UserSchedule.Repeat.NONE.value
        return repeat

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('category')
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if (category == UserSchedule.Category.SCHEDULE.value
                and start and end and end <= start):
            raise ValidationError('结束时间必须晚于开始时间。')
        repeat = cleaned.get('repeat')
        if repeat and repeat != UserSchedule.Repeat.NONE.value:
            repeat_end = cleaned.get('repeat_end')
            base_date = cleaned.get('date')
            if not repeat_end:
                raise ValidationError('重复项必须填写结束日期。')
            if base_date and repeat_end < base_date:
                raise ValidationError('重复结束日期不能早于开始日期。')
        return cleaned


def _occurrence_dates(base_date, repeat, repeat_end):
    """计算重复项的全部发生日期（含 base_date）。"""
    if repeat == UserSchedule.Repeat.NONE.value:
        return [base_date]
    if repeat_end is None or repeat_end < base_date:
        raise ValidationError('重复项必须填写有效的结束日期。')
    step = timedelta(days=1) if repeat == UserSchedule.Repeat.DAILY.value \
        else timedelta(days=7)
    dates, d = [], base_date
    while d <= repeat_end:
        dates.append(d)
        d += step
        if len(dates) > UserSchedule.MAX_OCCURRENCES:
            raise ValidationError('重复次数过多，请缩短结束日期。')
    return dates


def _materialize_schedule(me, cd):
    """按 cleaned_data 实体化手动日程（重复项展开为多行共享 series_id）。

    返回 (创建数量, 主日期)，供重定向使用。
    """
    dates = _occurrence_dates(cd['date'], cd['repeat'], cd.get('repeat_end'))
    # 待办不携带时间信息
    is_todo = cd['category'] == UserSchedule.Category.TODO.value
    start_time = None if is_todo else cd['start_time']
    end_time = None if is_todo else cd['end_time']
    series = uuid.uuid4().hex if len(dates) > 1 else ''
    with transaction.atomic():
        for d in dates:
            UserSchedule.objects.create(
                person=me,
                title=cd['title'],
                category=cd['category'],
                date=d,
                start_time=start_time,
                end_time=end_time,
                location=cd['location'],
                note=cd['note'],
                color=cd['color'],
                repeat=cd['repeat'],
                repeat_end=cd.get('repeat_end'),
                series_id=series,
            )
    return len(dates), cd['date']



class mySchedule(ProfileTemplateView):
    """个人日程表，聚合三类来源的时间安排。"""

    template_name = 'schedule/index.html'
    page_name = '我的日程表'
    http_method_names = ['get']

    # 各源事件配色
    _COLOR_COURSE = '#4361ee'        # 书院课程（已发布活动）
    _COLOR_PLANNED = '#8ba3f0'       # 书院课表（尚未发布活动的周次）
    _COLOR_ACTIVITY = '#2ecc71'      # 报名活动
    _COLOR_APPOINT = '#f39c12'       # 地下室预约
    _COLOR_ACADEMIC = '#9b59b6'      # 教务课表（门户导入）
    _COLOR_MANUAL = '#16a085'        # 手动日程

    def _collect_participation_events(self, me: NaturalPerson):
        """已报名/已选课且活动已生成的日程。"""
        now = datetime.now()
        events = []
        participations = (
            Participation.objects.activated()
            .filter(person=me, activity__end__gt=now)
            .exclude(activity__status__in=[
                Activity.Status.CANCELED,
                Activity.Status.ABORT,
            ])
            .select_related('activity')
        )
        for p in participations:
            act = p.activity
            if act.category == Activity.ActivityCategory.COURSE:
                color, category = self._COLOR_COURSE, '书院课程'
            else:
                color, category = self._COLOR_ACTIVITY, '报名活动'
            events.append({
                'title': act.title,
                'start': act.start.strftime('%Y-%m-%dT%H:%M:%S'),
                'end': act.end.strftime('%Y-%m-%dT%H:%M:%S'),
                'color': color,
                'category': category,
                'location': act.location or '未设置',
                'url': f'/viewActivity/{act.id}',
            })
        return events

    def _collect_planned_course_events(self, me: NaturalPerson):
        """课表：已选上但尚未发布课程活动的未来周次。

        课程活动由定时任务逐周生成（CourseTime.cur_week 记录已生成周数），
        因此仅靠活动无法展示整学期课表，这里按周展开补全。
        """
        now = datetime.now()
        events = []
        courses = Course.objects.activated().filter(
            participant_set__person=me,
            participant_set__status=CourseParticipant.Status.SUCCESS,
        ).prefetch_related('time_set')
        for course in courses:
            for course_time in course.time_set.all():
                # 已生成的周次为 [0, cur_week)，其余周次尚未产生活动
                for week in range(course_time.cur_week, course_time.end_week):
                    start = course_time.start + timedelta(days=7 * week)
                    end = course_time.end + timedelta(days=7 * week)
                    if end <= now:
                        continue
                    events.append({
                        'title': course.name,
                        'start': start.strftime('%Y-%m-%dT%H:%M:%S'),
                        'end': end.strftime('%Y-%m-%dT%H:%M:%S'),
                        'color': self._COLOR_PLANNED,
                        'category': '书院课表（未发布）',
                        'location': '以课程活动发布为准',
                    })
        return events

    def _collect_appointment_events(self, user):
        """地下室房间预约。"""
        events = []
        appoints = get_appoints(user, 'future')
        if not appoints:
            return events
        for appoint in appoints.select_related('Room'):
            room = appoint.Room.Rtitle if appoint.Room_id else '未知房间'
            events.append({
                'title': f'地下室：{room}',
                'start': appoint.Astart.strftime('%Y-%m-%dT%H:%M:%S'),
                'end': appoint.Afinish.strftime('%Y-%m-%dT%H:%M:%S'),
                'color': self._COLOR_APPOINT,
                'category': '地下室预约',
                'location': room,
                'url': '/underground/',
            })
        return events

    def _collect_academic_course_events(self, me: NaturalPerson):
        """教务课表（同学从门户导入）。按周展开为日历事件。"""
        now = datetime.now()
        events = []
        courses = AcademicCourse.objects.filter(person=me)
        for course in courses:
            semester_start = course.semester_start
            parity = {AcademicCourse.Parity.ALL: 'ALL',
                      AcademicCourse.Parity.ODD: 'ODD',
                      AcademicCourse.Parity.EVEN: 'EVEN'}[course.parity]
            lesson = {
                'day_of_week': course.day_of_week,
                'start_section': course.start_section,
                'end_section': course.end_section,
                'start_time': course.start_time.strftime('%H:%M'),
                'end_time': course.end_time.strftime('%H:%M'),
                'week_start': course.week_start,
                'week_end': course.week_end,
                'parity': parity,
                'name': course.name,
                'room': course.room,
                'teacher': course.teacher,
            }
            for ev in expand_lesson_to_events(lesson, semester_start, now):
                ev.update({
                    'color': self._COLOR_ACADEMIC,
                    'category': '教务课表',
                })
                events.append(ev)
        return events

    def _collect_manual_events(self, me: NaturalPerson):
        """手动日程（SCHEDULE 类）作为第5数据源进入日历。"""
        events = []
        items = UserSchedule.objects.filter(
            person=me, category=UserSchedule.Category.SCHEDULE.value)
        for item in items:
            if item.start_time:
                start = datetime.combine(item.date, item.start_time)
                end = datetime.combine(
                    item.date, item.end_time or item.start_time)
                all_day = False
            else:
                # 全天事件：用 date-only 字符串并标记 allDay
                start = item.date
                end = item.date + timedelta(days=1)
                all_day = True
            events.append({
                'id': f'manual-{item.id}',
                'title': item.title,
                'start': start.strftime('%Y-%m-%d' if all_day else '%Y-%m-%dT%H:%M:%S'),
                'end': end.strftime('%Y-%m-%d' if all_day else '%Y-%m-%dT%H:%M:%S'),
                'allDay': all_day,
                'color': item.color or self._COLOR_MANUAL,
                'category': '手动日程',
                'location': item.location or '未设置',
                'url': f'/schedule/editItem/{item.id}/',
            })
        return events

    def prepare_get(self):
        html_display = {}
        # 透传 PRG 重定向带来的提示消息（来自 add/edit/delete/toggle 视图）
        transfer_message_context(self.request.GET, self.extra_context)
        if not self.request.user.is_person():
            html_display['warn_code'] = 1
            html_display['warn_message'] = '日程表仅对个人用户开放！'
            self.extra_context.update(
                html_display=html_display, schedule_events=[],
                selected_date_str=date.today().strftime('%Y-%m-%d'),
                todos=[])
            return self.get

        me = NaturalPerson.objects.get(person_id=self.request.user)

        # 选中的日期（用于当日待办面板与日历定位），默认今天
        date_str = (self.request.GET.get('date') or '').strip()
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            selected_date = date.today()

        events = self._collect_participation_events(me)
        events += self._collect_planned_course_events(me)
        events += self._collect_appointment_events(self.request.user)
        events += self._collect_academic_course_events(me)
        events += self._collect_manual_events(me)
        events.sort(key=lambda e: e['start'])

        todos = UserSchedule.objects.filter(
            person=me,
            category=UserSchedule.Category.TODO.value,
            date=selected_date,
        ).order_by('done', 'start_time', 'id')

        self.extra_context.update(
            html_display=html_display,
            schedule_events=events,
            selected_date=selected_date,
            selected_date_str=selected_date.strftime('%Y-%m-%d'),
            todos=todos,
            add_form=UserScheduleForm(
                initial={'date': selected_date, 'color': '#16a085'}))
        return self.get

    def get(self):
        return self.render()


@method_decorator(csrf_protect, name='dispatch')
class importCourseTable(ProfileTemplateView):
    """导入教务课表：上传门户「我的课表」HTML，解析后存入本人课表。

    全局 CsrfViewMiddleware 已禁用，故显式应用 csrf_protect（AGENTS.md 约定）。
    """

    template_name = 'schedule/upload.html'
    page_name = '导入教务课表'
    http_method_names = ['get', 'post']

    def prepare_get(self):
        self.extra_context['html_display'] = {}
        return self.get

    def prepare_post(self):
        html_display = {}
        if not self.request.user.is_person():
            wrong('导入课表仅对个人用户开放！', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        me = NaturalPerson.objects.get(person_id=self.request.user)

        # 1) 读取上传文件（仅在内存中解析，绝不落盘）
        upload = self.request.FILES.get('course_html')
        if upload is None or upload.size == 0:
            wrong('请先选择门户课表 HTML 文件再上传。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post
        if upload.size > _MAX_UPLOAD_BYTES:
            wrong('文件过大，请确保上传的是门户课表页面（.html）。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post
        try:
            raw = upload.read().decode('utf-8', errors='ignore')
        except Exception:
            wrong('文件读取失败，请确认上传的是有效的 HTML 文件。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 2) 学期第一周周一（必填）
        semester_start_str = (self.request.POST.get('semester_start') or '').strip()
        try:
            semester_start = datetime.strptime(
                semester_start_str, '%Y-%m-%d').date()
        except Exception:
            wrong('请填写学期第 1 教学周对应的周一日期（格式 YYYY-MM-DD）。',
                  html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 3) 解析
        lessons = parse_pku_course_html(raw)
        if not lessons:
            wrong('未能从文件中解析到课程，请确认上传的是门户「我的课表」页面。',
                  html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 4) 覆盖式写入（同一同学重新导入即替换）
        # term 为用户自由输入，超出列宽会在 MySQL 严格模式下直接报错，
        # 且删除已在同一事务内，必须先校验再落库。
        term = (self.request.POST.get('term') or '').strip()
        if len(term) > _TERM_MAX_LENGTH:
            wrong(f'学期名称过长（最多 {_TERM_MAX_LENGTH} 个字符）。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 删除旧课表与写入新课表必须原子完成，否则中途失败会让同学的课表
        # 变成空表或半截数据。
        try:
            with transaction.atomic():
                AcademicCourse.objects.filter(person=me).delete()
                AcademicCourse.objects.bulk_create([
                    AcademicCourse(
                        person=me,
                        name=lesson['name'],
                        teacher=lesson['teacher'],
                        room=lesson['room'],
                        day_of_week=lesson['day_of_week'],
                        start_section=lesson['start_section'],
                        end_section=lesson['end_section'],
                        start_time=datetime.strptime(
                            lesson['start_time'], '%H:%M').time(),
                        end_time=datetime.strptime(
                            lesson['end_time'], '%H:%M').time(),
                        week_start=lesson['week_start'],
                        week_end=lesson['week_end'],
                        parity=_PARITY_MAP.get(
                            lesson['parity'], AcademicCourse.Parity.ALL),
                        semester_start=semester_start,
                        term=term,
                    )
                    for lesson in lessons
                ])
        except Exception:
            wrong('课表写入失败，原有课表已保留，请稍后重试或确认文件内容。',
                  html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        succeed(f'已成功导入 {len(lessons)} 门课程，可在「我的日程表」查看。',
                 html_display)
        self.extra_context.update(html_display=html_display)
        return self.post

    def get(self):
        return self.render()

    def post(self):
        return self.render()


# ---------------------------------------------------------------------------
# 手动日程 / 待办的写操作视图（PRG：写后重定向回日程页，提示随 URL 传递）
# ---------------------------------------------------------------------------
def _require_person_or_redirect(view, fallback='/schedule/'):
    """非个人用户直接重定向，返回 (person, None) 或 (None, redirect_response)。"""
    if not view.request.user.is_person():
        return None, view.redirect(fallback)
    return NaturalPerson.objects.get(person_id=view.request.user), None


def _form_errors_message(form):
    parts = []
    for field, errs in form.errors.items():
        parts.append(' '.join(str(e) for e in errs))
    return '；'.join(parts) or '表单填写有误。'


@method_decorator(csrf_protect, name='dispatch')
class addScheduleItem(ProfileTemplateView):
    """快速添加手动日程/待办（内联表单 POST）。

    全局 CsrfViewMiddleware 已禁用，故显式应用 csrf_protect（AGENTS.md 约定）。
    """
    http_method_names = ['post']

    def prepare_post(self):
        me, resp = _require_person_or_redirect(self)
        if resp is not None:
            return resp
        form = UserScheduleForm(self.request.POST)
        if not form.is_valid():
            return self.redirect(message_url(
                wrong(_form_errors_message(form)), '/schedule/'))
        cd = form.cleaned_data
        try:
            count, base_date = _materialize_schedule(me, cd)
        except ValidationError as e:
            return self.redirect(message_url(
                wrong(str(e)), '/schedule/'))
        is_todo = cd['category'] == UserSchedule.Category.TODO.value
        ok = f'已添加 {count} 条待办。' if is_todo else f'已添加 {count} 条日程。'
        return self.redirect(message_url(
            succeed(ok), f'/schedule/?date={base_date}'))


@method_decorator(csrf_protect, name='dispatch')
class editScheduleItem(ProfileTemplateView):
    """编辑单条手动日程/待办。

    全局 CsrfViewMiddleware 已禁用，故显式应用 csrf_protect（AGENTS.md 约定）。
    """
    template_name = 'schedule/item_form.html'
    page_name = '编辑日程'
    http_method_names = ['get', 'post']

    def _get_item(self):
        me = NaturalPerson.objects.get(person_id=self.request.user)
        return get_object_or_404(
            UserSchedule, pk=self.kwargs['pk'], person=me)

    def prepare_get(self):
        if not self.request.user.is_person():
            return self.redirect('/schedule/')
        transfer_message_context(self.request.GET, self.extra_context)
        item = self._get_item()
        self.extra_context.update(
            form=UserScheduleForm(instance=item), item=item, is_edit=True)
        return self.render()

    def prepare_post(self):
        if not self.request.user.is_person():
            return self.redirect('/schedule/')
        item = self._get_item()
        form = UserScheduleForm(self.request.POST, instance=item)
        if not form.is_valid():
            return self.redirect(message_url(
                wrong(_form_errors_message(form)),
                f'/schedule/editItem/{item.id}/'))
        inst = form.save(commit=False)
        if inst.category == UserSchedule.Category.TODO.value:
            inst.start_time = None
            inst.end_time = None
        inst.save()
        return self.redirect(message_url(
            succeed('已保存修改。'), f'/schedule/?date={inst.date}'))


@method_decorator(csrf_protect, name='dispatch')
class deleteScheduleItem(ProfileTemplateView):
    """删除单条日程/待办；若属于某重复系列且勾选 delete_series 则整系列删除。

    全局 CsrfViewMiddleware 已禁用，故显式应用 csrf_protect（AGENTS.md 约定）。
    """
    http_method_names = ['post']

    def prepare_post(self):
        me, resp = _require_person_or_redirect(self)
        if resp is not None:
            return resp
        item = get_object_or_404(
            UserSchedule, pk=self.kwargs['pk'], person=me)
        target_date = item.date
        if self.request.POST.get('delete_series') and item.series_id:
            n = UserSchedule.objects.filter(
                person=me, series_id=item.series_id).count()
            UserSchedule.objects.filter(
                person=me, series_id=item.series_id).delete()
            return self.redirect(message_url(
                succeed(f'已删除整个系列（共 {n} 条）。'),
                f'/schedule/?date={target_date}'))
        item.delete()
        return self.redirect(message_url(
            succeed('已删除该条目。'), f'/schedule/?date={target_date}'))


@method_decorator(csrf_protect, name='dispatch')
class toggleTodo(ProfileTemplateView):
    """切换待办完成状态（POST）。

    全局 CsrfViewMiddleware 已禁用，故显式应用 csrf_protect（AGENTS.md 约定）。
    """
    http_method_names = ['post']

    def prepare_post(self):
        me, resp = _require_person_or_redirect(self)
        if resp is not None:
            return resp
        item = get_object_or_404(
            UserSchedule, pk=self.kwargs['pk'], person=me,
            category=UserSchedule.Category.TODO.value)
        item.done = not item.done
        item.save()
        return self.redirect(f'/schedule/?date={item.date}')


class manageSchedule(ProfileTemplateView):
    """管理我的日程：列出全部手动日程/待办，提供编辑/删除入口。"""
    template_name = 'schedule/manage.html'
    page_name = '管理我的日程'
    http_method_names = ['get']

    def prepare_get(self):
        transfer_message_context(self.request.GET, self.extra_context)
        if not self.request.user.is_person():
            return self.redirect('/schedule/')
        me = NaturalPerson.objects.get(person_id=self.request.user)
        items = UserSchedule.objects.filter(person=me)
        self.extra_context.update(items=items)
        return self.render()
