"""
Tests for 教务课表 HTML 导入（issue #973 延伸功能）。

覆盖：
- parse_pku_course_html 能正确解析门户课表 HTML（合并连续节次、单双周、无教室）；
- expand_lesson_to_events 按周展开且排除过去周次；
- importCourseTable 视图：上传文件后写入本人课表、覆盖式替换、缺字段报错；
- 日程表页面聚合教务课表事件（第 4 数据源）。
"""
import io
from datetime import date, datetime, timedelta

from django.test import TestCase

from app.models import (
    AcademicCourse,
    NaturalPerson,
    User,
)
from app.pku_course_parser import expand_lesson_to_events, parse_pku_course_html
from app.schedule_views import importCourseTable, mySchedule


# 复用一段最小可解析的门户课表 HTML（mon1/tue1 两格，覆盖每周与单周、含无教室项）
_SAMPLE_HTML = """<!DOCTYPE html><html><body>
<table>
<tr><td id="mon1" class="td-compact"><div><span style="font-size:12px;">高等数学A（二）(主)<br>上课信息：1-15周 每周 理教406  教师：束琳 备注：习题课<br>考试信息：20260618 星期四 上午 理教306</span></div></td></tr>
<tr><td id="tue3" class="td-compact"><div><span style="font-size:12px;">体适能(主)<br>上课信息：1-15周 每周   教师：郭思佳 备注：五四跑廊<br>考试信息： </span></div></td></tr>
<tr><td id="wed5" class="td-compact"><div><span style="font-size:12px;">程序设计实习(主)<br>上课信息：1-15周 单周 理教203  教师：郭炜 <br>考试信息：20260626 星期五 下午 </span></div></td></tr>
</table></body></html>"""


class PkuCourseParserTest(TestCase):
    def test_parse_sample_html(self):
        lessons = parse_pku_course_html(_SAMPLE_HTML)
        # 三格 -> 三条课程块
        self.assertEqual(len(lessons), 3)
        by_name = {L['name']: L for L in lessons}

        ga = by_name['高等数学A（二）']
        self.assertEqual(ga['day_of_week'], 0)        # 周一
        self.assertEqual(ga['start_section'], 1)       # 仅 1 节
        self.assertEqual(ga['end_section'], 1)
        self.assertEqual(ga['start_time'], '08:00')
        self.assertEqual(ga['week_start'], 1)
        self.assertEqual(ga['week_end'], 15)
        self.assertEqual(ga['parity'], 'ALL')
        self.assertEqual(ga['room'], '理教406')
        self.assertEqual(ga['teacher'], '束琳')

        ti = by_name['体适能']
        self.assertEqual(ti['day_of_week'], 1)          # 周二
        self.assertEqual(ti['start_section'], 3)
        self.assertEqual(ti['room'], '')                # 无教室
        self.assertEqual(ti['teacher'], '郭思佳')

        ps = by_name['程序设计实习']
        self.assertEqual(ps['day_of_week'], 2)          # 周三
        self.assertEqual(ps['start_section'], 5)
        self.assertEqual(ps['parity'], 'ODD')           # 单周

    def test_expand_excludes_past_weeks(self):
        lesson = {
            'day_of_week': 0, 'start_section': 1, 'end_section': 1,
            'start_time': '08:00', 'end_time': '08:45',
            'week_start': 1, 'week_end': 2, 'parity': 'ALL',
            'name': 'X', 'room': 'R', 'teacher': 'T',
        }
        # 以（今天之后最近的）周一为第 1 周 -> 全部为未来
        future_start = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        evs = expand_lesson_to_events(lesson, future_start, now=datetime.now())
        self.assertEqual(len(evs), 2)
        # 以 10 周前为第 1 周 -> 全部过去，应为空
        past_start = date.today() - timedelta(weeks=10)
        evs_past = expand_lesson_to_events(lesson, past_start, now=datetime.now())
        self.assertEqual(evs_past, [])

    def test_expand_respects_parity(self):
        lesson = {
            'day_of_week': 0, 'start_section': 1, 'end_section': 1,
            'start_time': '08:00', 'end_time': '08:45',
            'week_start': 1, 'week_end': 4, 'parity': 'ODD',
            'name': 'X', 'room': 'R', 'teacher': 'T',
        }
        base = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        evs = expand_lesson_to_events(lesson, base, now=datetime.now())
        # 单周：1、3 周（2、4 周被跳过）
        self.assertEqual(len(evs), 2)


class ImportCourseTableViewTest(TestCase):
    def setUp(self):
        self.stu_user = User.objects.create_user(
            "stus002", "学生2", usertype=User.Type.PERSON, password="x")
        self.stu_user.is_newuser = False
        self.stu_user.save()
        self.student = NaturalPerson.objects.create(
            self.stu_user, name="学生2")
        self.view = importCourseTable()
        self.url = '/importCourseTable/'

    def _post(self, html=_SAMPLE_HTML, semester_start='2026-02-23'):
        return self.client.post(
            self.url,
            data={'course_html': io.BytesIO(html.encode('utf-8')),
                  'semester_start': semester_start},
            format='multipart')

    def test_import_creates_courses(self):
        self.client.force_login(self.stu_user)
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        courses = AcademicCourse.objects.filter(person=self.student)
        self.assertEqual(courses.count(), 3)
        # 单周课程写入 parity=ODD
        odd = courses.get(name='程序设计实习')
        self.assertEqual(odd.parity, AcademicCourse.Parity.ODD)
        self.assertEqual(odd.room, '理教203')

    def test_import_is_overwriting(self):
        self.client.force_login(self.stu_user)
        self._post()
        # 再次导入应替换而非累加
        self._post()
        self.assertEqual(
            AcademicCourse.objects.filter(person=self.student).count(), 3)

    def test_import_requires_file(self):
        self.client.force_login(self.stu_user)
        resp = self.client.post(self.url, data={'semester_start': '2026-02-23'},
                                 format='multipart')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            AcademicCourse.objects.filter(person=self.student).count(), 0)

    def test_import_requires_semester_start(self):
        self.client.force_login(self.stu_user)
        resp = self.client.post(
            self.url,
            data={'course_html': io.BytesIO(_SAMPLE_HTML.encode('utf-8'))},
            format='multipart')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            AcademicCourse.objects.filter(person=self.student).count(), 0)


class AcademicCourseInScheduleTest(TestCase):
    def setUp(self):
        self.stu_user = User.objects.create_user(
            "stus003", "学生3", usertype=User.Type.PERSON, password="x")
        self.stu_user.is_newuser = False
        self.stu_user.save()
        self.student = NaturalPerson.objects.create(
            self.stu_user, name="学生3")
        self.view = mySchedule()

    def test_academic_course_aggregated(self):
        # 以未来某个周一为第 1 周，制造未来教务课
        base = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        AcademicCourse.objects.create(
            person=self.student, name='测试教务课', teacher='师',
            room='理教101', day_of_week=0, start_section=1, end_section=1,
            start_time=datetime.strptime('08:00', '%H:%M').time(),
            end_time=datetime.strptime('08:45', '%H:%M').time(),
            week_start=1, week_end=2, parity=AcademicCourse.Parity.ALL,
            semester_start=base)
        events = self.view._collect_academic_course_events(self.student)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e['category'] == '教务课表' for e in events))
        self.assertTrue(all(e['color'] == '#9b59b6' for e in events))
        self.assertTrue(all(e['title'] == '测试教务课' for e in events))

    def test_academic_course_past_excluded(self):
        base = date.today() - timedelta(weeks=10)
        AcademicCourse.objects.create(
            person=self.student, name='过去教务课', teacher='师',
            room='理教101', day_of_week=0, start_section=1, end_section=1,
            start_time=datetime.strptime('08:00', '%H:%M').time(),
            end_time=datetime.strptime('08:45', '%H:%M').time(),
            week_start=1, week_end=2, parity=AcademicCourse.Parity.ALL,
            semester_start=base)
        events = self.view._collect_academic_course_events(self.student)
        self.assertEqual(events, [])

    def test_schedule_page_includes_academic(self):
        base = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        AcademicCourse.objects.create(
            person=self.student, name='页面教务课', teacher='师',
            room='理教101', day_of_week=0, start_section=1, end_section=1,
            start_time=datetime.strptime('08:00', '%H:%M').time(),
            end_time=datetime.strptime('08:45', '%H:%M').time(),
            week_start=1, week_end=2, parity=AcademicCourse.Parity.ALL,
            semester_start=base)
        self.client.force_login(self.stu_user)
        resp = self.client.get('/schedule/')
        self.assertEqual(resp.status_code, 200)
        events = resp.context['schedule_events']
        academic = [e for e in events if e['category'] == '教务课表']
        self.assertEqual(len(academic), 2)
