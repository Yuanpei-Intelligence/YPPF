"""Tests for YQPoint pool helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import connection
from django.test import TestCase

from app.models import NaturalPerson, Pool
from app.YQPoint_utils import check_user_pool
from generic.models import User


class CheckUserPoolTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='S900001',
            name='池测',
            password='test',
        )
        NaturalPerson.objects.create(self.user, name='池测')
        now = datetime.now()
        self.pool = Pool.objects.create(
            title='测试奖池',
            type=Pool.Type.EXCHANGE,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )

    def test_dangling_activity_fk_treated_as_no_activity(self):
        with connection.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            cursor.execute(
                'UPDATE `app_pool` SET `activity_id`=%s WHERE `id`=%s',
                [9_999_999, self.pool.pk],
            )
            cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.activity_id, 9_999_999)
        self.assertIsNone(check_user_pool(self.user, self.pool))
