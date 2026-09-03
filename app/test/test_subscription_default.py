"""
Regression tests for issue #973-1: 新账号默认只订阅学院机构与已加入的小组。

订阅以反向黑名单 NaturalPerson.unsubscribe_list 实现(空名单=订阅全部)。
本测试覆盖：
- 新账号默认不订阅未加入的小组，但订阅学院机构(allow_unsubscribe=False)；
- 已加入小组(active Position)会被默认订阅；
- subscribe_org / unsubscribe_org 在加入/退出小组时维护订阅状态。
"""
from django.test import TestCase

from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
)
from app.org_utils import (
    set_default_subscription,
    subscribe_org,
    unsubscribe_org,
)
from boot.config import GLOBAL_CONFIG
from generic.models import User


class SubscriptionDefaultTest(TestCase):
    def setUp(self):
        # 学院机构：强制订阅(allow_unsubscribe=False)
        self.college_user = User.objects.create_user(
            "college001", "元培学院", usertype=User.Type.ORG, password="x")
        self.college_type = OrganizationType.objects.create(
            otype_id=0, otype_name="元培学院", allow_unsubscribe=False)
        self.college = Organization.objects.create(
            organization_id=self.college_user, oname="元培学院",
            otype=self.college_type, status=True)
        # 普通小组：允许退订
        self.group_user = User.objects.create_user(
            "group001", "测试小组", usertype=User.Type.ORG, password="x")
        self.group_type = OrganizationType.objects.create(
            otype_id=1, otype_name="测试小组", allow_unsubscribe=True)
        self.group = Organization.objects.create(
            organization_id=self.group_user, oname="测试小组",
            otype=self.group_type, status=True)
        # 学生
        self.stu_user = User.objects.create_user(
            "stu001", "测试学生", usertype=User.Type.PERSON, password="x")
        self.student = NaturalPerson.objects.create(
            self.stu_user, name="测试学生")

    def test_new_account_subscribes_only_to_college(self):
        set_default_subscription(self.student)
        # 学院机构应被订阅(不在不订阅名单)
        self.assertFalse(
            self.student.unsubscribe_list.filter(id=self.college.id).exists())
        # 未加入的小组不应被订阅(在不订阅名单)
        self.assertTrue(
            self.student.unsubscribe_list.filter(id=self.group.id).exists())
        # 未加入任何小组时，仅学院机构被订阅
        self.assertEqual(self.student.unsubscribe_list.count(), 1)

    def test_joined_group_is_subscribed_by_default(self):
        Position.objects.create(
            person=self.student, org=self.group,
            year=GLOBAL_CONFIG.acadamic_year, semester=GLOBAL_CONFIG.semester,
            status=Position.Status.INSERVICE)
        set_default_subscription(self.student)
        self.assertFalse(
            self.student.unsubscribe_list.filter(id=self.group.id).exists())
        self.assertFalse(
            self.student.unsubscribe_list.filter(id=self.college.id).exists())
        self.assertEqual(self.student.unsubscribe_list.count(), 0)

    def test_subscribe_org_removes_from_unsubscribe_list(self):
        set_default_subscription(self.student)
        self.assertTrue(
            self.student.unsubscribe_list.filter(id=self.group.id).exists())
        subscribe_org(self.student, self.group)
        self.assertFalse(
            self.student.unsubscribe_list.filter(id=self.group.id).exists())

    def test_unsubscribe_org_adds_to_unsubscribe_list(self):
        set_default_subscription(self.student)
        subscribe_org(self.student, self.group)
        unsubscribe_org(self.student, self.group)
        self.assertTrue(
            self.student.unsubscribe_list.filter(id=self.group.id).exists())
