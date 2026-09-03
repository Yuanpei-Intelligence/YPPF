"""
Tests for issue #973-3: 日程表页面（整合书院课时间、报名活动时间与课表）。

覆盖：
- 已报名的普通活动出现在日程中，且标记为"报名活动"；
- 已生成的课程活动出现在日程中，且标记为"书院课程"；
- 已选上但尚未发布活动的未来周次(课表)按周展开补齐；
- 已结束的活动不进入日程；
- 页面可正常访问并渲染。
"""
from datetime import datetime, timedelta

from django.test import TestCase

from app.models import (
    Activity,
    Course,
    CourseParticipant,
    CourseTime,
    NaturalPerson,
    Organization,
    OrganizationType,
    Participation,
)
from app.schedule_views import mySchedule
from boot.config import GLOBAL_CONFIG
from generic.models import User


class ScheduleTest(TestCase):
    def setUp(self):
        self.now = datetime.now()
        # 组织
        self.org_user = User.objects.create_user(
            "orgs001", "日程组织", usertype=User.Type.ORG, password="x")
        self.otype = OrganizationType.objects.create(
            otype_id=20, otype_name="学生小组", allow_unsubscribe=True)
        self.org = Organization.objects.create(
            organization_id=self.org_user, oname="日程组织",
            otype=self.otype, status=True)
        # 审核老师
        self.teacher_user = User.objects.create_user(
            "teas001", "老师", usertype=User.Type.PERSON, password="x")
        self.teacher = NaturalPerson.objects.create(
            self.teacher_user, name="老师")
        # 学生
        self.stu_user = User.objects.create_user(
            "stus001", "学生", usertype=User.Type.PERSON, password="x")
        # 新用户会被重定向到用户协议页，这里模拟已完成首次登录
        self.stu_user.is_newuser = False
        self.stu_user.save()
        self.student = NaturalPerson.objects.create(
            self.stu_user, name="学生")
        self.view = mySchedule()

    def _create_activity(self, title, start_delta, category, location=""):
        return Activity.objects.create(
            title=title,
            organization_id=self.org,
            examine_teacher=self.teacher,
            start=self.now + start_delta,
            end=self.now + start_delta + timedelta(hours=2),
            status=Activity.Status.WAITING,
            category=category,
            location=location,
            need_apply=False,
            capacity=50,
            current_participants=0)

    def test_future_normal_activity_in_schedule(self):
        activity = self._create_activity(
            "未来活动", timedelta(days=2),
            Activity.ActivityCategory.NORMAL, location="B107")
        Participation.objects.create(
            activity=activity, person=self.student,
            status=Participation.AttendStatus.APPLYSUCCESS)
        events = self.view._collect_participation_events(self.student)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['title'], "未来活动")
        self.assertEqual(events[0]['category'], "报名活动")
        self.assertEqual(events[0]['location'], "B107")
        self.assertEqual(events[0]['url'], f'/viewActivity/{activity.id}')

    def test_past_activity_excluded(self):
        activity = self._create_activity(
            "过去活动", timedelta(days=-5),
            Activity.ActivityCategory.NORMAL)
        Participation.objects.create(
            activity=activity, person=self.student,
            status=Participation.AttendStatus.ATTENDED)
        events = self.view._collect_participation_events(self.student)
        self.assertEqual(events, [])

    def test_canceled_participation_excluded(self):
        activity = self._create_activity(
            "已放弃活动", timedelta(days=2),
            Activity.ActivityCategory.NORMAL)
        Participation.objects.create(
            activity=activity, person=self.student,
            status=Participation.AttendStatus.CANCELED)
        events = self.view._collect_participation_events(self.student)
        self.assertEqual(events, [])

    def test_course_activity_marked_as_course(self):
        activity = self._create_activity(
            "书院课-第1次课", timedelta(days=1),
            Activity.ActivityCategory.COURSE)
        Participation.objects.create(
            activity=activity, person=self.student,
            status=Participation.AttendStatus.APPLYSUCCESS)
        events = self.view._collect_participation_events(self.student)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['category'], "书院课程")

    def test_planned_course_weeks_expanded(self):
        """尚未发布活动的周次应按周展开进入课表。"""
        course = Course.objects.create(
            name="测试书院课", organization=self.org,
            year=GLOBAL_CONFIG.acadamic_year,
            semester=GLOBAL_CONFIG.semester,
            type=Course.CourseType.OTHER, capacity=30,
            status=Course.Status.SELECT_END)
        # 第一周上课时间为一天后，共 4 周，已生成 1 周
        CourseTime.objects.create(
            course=course,
            start=self.now + timedelta(days=1),
            end=self.now + timedelta(days=1, hours=2),
            cur_week=1, end_week=4)
        CourseParticipant.objects.create(
            course=course, person=self.student,
            status=CourseParticipant.Status.SUCCESS)
        events = self.view._collect_planned_course_events(self.student)
        # 剩余未生成的周次为第 2、3、4 周，共 3 条
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e['title'] == "测试书院课" for e in events))
        self.assertTrue(
            all(e['category'] == "书院课表（未发布）" for e in events))

    def test_unselected_course_not_in_schedule(self):
        course = Course.objects.create(
            name="没选上的课", organization=self.org,
            year=GLOBAL_CONFIG.acadamic_year,
            semester=GLOBAL_CONFIG.semester,
            type=Course.CourseType.OTHER, capacity=30,
            status=Course.Status.SELECT_END)
        CourseTime.objects.create(
            course=course,
            start=self.now + timedelta(days=1),
            end=self.now + timedelta(days=1, hours=2),
            cur_week=0, end_week=4)
        CourseParticipant.objects.create(
            course=course, person=self.student,
            status=CourseParticipant.Status.FAILED)
        events = self.view._collect_planned_course_events(self.student)
        self.assertEqual(events, [])

    def test_no_appointment_returns_empty(self):
        """未注册地下室身份时不应报错。"""
        events = self.view._collect_appointment_events(self.stu_user)
        self.assertEqual(events, [])

    def test_schedule_page_renders(self):
        activity = self._create_activity(
            "页面渲染活动", timedelta(days=2),
            Activity.ActivityCategory.NORMAL)
        Participation.objects.create(
            activity=activity, person=self.student,
            status=Participation.AttendStatus.APPLYSUCCESS)
        self.client.force_login(self.stu_user)
        response = self.client.get('/schedule/')
        self.assertEqual(response.status_code, 200)
        # 日历容器与事件数据均已注入
        self.assertContains(response, 'id="calendar"')
        self.assertContains(response, 'id="schedule-events"')
        events = response.context['schedule_events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['title'], "页面渲染活动")
        self.assertEqual(events[0]['url'], f'/viewActivity/{activity.id}')
