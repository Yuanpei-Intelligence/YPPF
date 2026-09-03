"""
Regression tests for issue #973-2: 书院课补选同学首次课签到优化。

课程活动在发布(建活动)时按当时选课名单一次性生成 Participation；补退选阶段
加入的同学不在快照中，导致首次课无法签到(需手动签到)。修复后：
- 补选成功会为已生成但尚未结束的课程活动增量补齐签到记录；
- 退选会清理未结束课程活动上的签到记录；
- 签到时(落点 B)对补选同学惰性补建，使其可正常签到。
"""
from datetime import datetime, timedelta

from django.test import TestCase

from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Course,
    CourseTime,
    Activity,
    Participation,
)
from app.course_utils import registration_status_change
from api.activity.checkin import do_checkin
from boot.config import GLOBAL_CONFIG
from generic.models import User


class CourseSigninBackfillTest(TestCase):
    def setUp(self):
        # 课程组织
        self.org_user = User.objects.create_user(
            "orgc001", "课程组织", usertype=User.Type.ORG, password="x")
        self.otype = OrganizationType.objects.create(
            otype_id=10, otype_name="学生小组", allow_unsubscribe=True)
        self.org = Organization.objects.create(
            organization_id=self.org_user, oname="课程组织",
            otype=self.otype, status=True)
        # 审核老师
        self.teacher_user = User.objects.create_user(
            "teac001", "老师", usertype=User.Type.PERSON, password="x")
        self.teacher = NaturalPerson.objects.create(self.teacher_user, name="老师")
        # 学生
        self.stu_user = User.objects.create_user(
            "stuc001", "学生", usertype=User.Type.PERSON, password="x")
        self.student = NaturalPerson.objects.create(self.stu_user, name="学生")
        # 课程(补退选阶段)
        self.course = Course.objects.create(
            name="测试书院课", organization=self.org,
            year=GLOBAL_CONFIG.acadamic_year, semester=GLOBAL_CONFIG.semester,
            type=Course.CourseType.OTHER, capacity=30,
            status=Course.Status.STAGE2)
        # 上课时间(第一周, 未来)
        now = datetime.now()
        self.ctime = CourseTime.objects.create(
            course=self.course,
            start=now + timedelta(days=3),
            end=now + timedelta(days=3, hours=2))
        # 模拟定时任务发布的第一课活动(当时名单不含本学生)
        self.activity = Activity.objects.create(
            title="测试书院课-第1次课",
            organization_id=self.org,
            examine_teacher=self.teacher,
            start=now + timedelta(days=3),
            end=now + timedelta(days=3, hours=2),
            status=Activity.Status.WAITING,
            category=Activity.ActivityCategory.COURSE,
            course_time=self.ctime,
            need_apply=False,
            # 与生产一致：create_single_course_activity 建课程活动时默认需签到，
            # 且 do_checkin 会前置校验 need_checkin。
            need_checkin=True,
            capacity=10,
            current_participants=10)

    def test_backfill_on_add(self):
        # 补选前：学生无该活动签到记录
        self.assertFalse(Participation.objects.filter(
            activity=self.activity, person=self.student).exists())
        # 补选
        registration_status_change(self.course.id, self.student, "select")
        # 补选后：应自动补齐签到记录
        self.assertTrue(Participation.objects.filter(
            activity=self.activity, person=self.student,
            status=Participation.AttendStatus.APPLYSUCCESS).exists())
        # 活动人数应+1
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.current_participants, 11)

    def test_signin_after_backfill(self):
        registration_status_change(self.course.id, self.student, "select")
        # 把活动置为进行中, 模拟开课, 验证补选学生可正常签到
        self.activity.status = Activity.Status.PROGRESSING
        self.activity.start = datetime.now() - timedelta(hours=1)
        self.activity.end = datetime.now() + timedelta(hours=1)
        self.activity.save()
        success, msg = do_checkin(self.student, self.activity.id)
        self.assertTrue(success)
        self.assertEqual(msg, "签到成功!")
        self.assertTrue(Participation.objects.filter(
            activity=self.activity, person=self.student,
            status=Participation.AttendStatus.ATTENDED).exists())

    def test_remove_on_withdraw(self):
        registration_status_change(self.course.id, self.student, "select")
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.current_participants, 11)
        # 退选
        registration_status_change(self.course.id, self.student, "cancel")
        # 签到记录应被清理
        self.assertFalse(Participation.objects.filter(
            activity=self.activity, person=self.student).exists())
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.current_participants, 10)
