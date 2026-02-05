"""
Tests for YQpools API.
"""
from datetime import datetime, timedelta
from random import randint
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status as http_status

from generic.models import User
from app.models import (
    Pool,
    PoolItem,
    PoolRecord,
    Prize,
    NaturalPerson,
    Organization,
    OrganizationType,
)
from app.YQPoint_utils import run_lottery
from app.config import CONFIG


class PoolsAPITestCase(APITestCase):
    """Test cases for Pools API endpoints."""

    def setUp(self):
        """Set up test data."""
        # Create test users
        self.user = User.objects.create_user(
            username=f'testuser{randint(1, 9999)}',
            password='testpass123',
            name='Test User',
            usertype=User.Type.PERSON,
        )
        self.user.YQpoint = 1000  # Give user some YQPoints
        self.user.save()

        # Create NaturalPerson for the user
        self.natural_person = NaturalPerson.objects.create(
            self.user, name='Test User'
        )

        # Create organization user for prize provider
        self.org_user = User.objects.create_user(
            username='orguser',
            password='orgpass123',
            name='Test Org',
            usertype=User.Type.ORG,
        )

        # Create OrganizationType and Organization
        org_type = OrganizationType.objects.create(
            otype_id=1,
            otype_name='Test Type',
            incharge=self.natural_person
        )
        self.organization = Organization.objects.create(
            organization_id=self.org_user,
            oname='Test Organization',
            otype=org_type
        )

        # Create YQPoint organization if configured (needed for run_lottery)
        if CONFIG.yqpoint.org_name:
            yqp_org_user = User.objects.create_user(
                username='yqp_org',
                password='yqppass123',
                name='YQPoint Org',
                usertype=User.Type.ORG,
            )
            Organization.objects.get_or_create(
                organization_id=yqp_org_user,
                defaults={
                    'oname': CONFIG.yqpoint.org_name,
                    'otype': org_type
                }
            )

        # Create test prizes
        self.prize1 = Prize.objects.create(
            name='Test Prize 1',
            provider=self.org_user,
            reference_price=100,
            stock=10,
            image='test1.jpg'
        )
        self.prize2 = Prize.objects.create(
            name='Test Prize 2',
            provider=self.org_user,
            reference_price=200,
            stock=5,
            image='test2.jpg'
        )
        self.prize3 = Prize.objects.create(
            name='Test Prize 3',
            provider=self.org_user,
            reference_price=50,
            stock=20,
            image='test3.jpg'
        )

        # Create test pools
        now = timezone.now()
        self.exchange_pool = Pool.objects.create(
            title='Test Exchange Pool',
            type=Pool.Type.EXCHANGE,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )

        self.lottery_pool = Pool.objects.create(
            title='Test Lottery Pool',
            type=Pool.Type.LOTTERY,
            entry_time=3,
            ticket_price=50,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )

        self.random_pool = Pool.objects.create(
            title='Test Random Pool',
            type=Pool.Type.RANDOM,
            entry_time=2,
            ticket_price=30,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
            empty_YQPoint_compensation_lowerbound=10,
            empty_YQPoint_compensation_upperbound=20,
        )

        # Create pool items
        self.exchange_item1 = PoolItem.objects.create(
            pool=self.exchange_pool,
            prize=self.prize1,
            origin_num=10,
            consumed_num=0,
            exchange_price=100,
            exchange_limit=1,
        )

        self.exchange_item2 = PoolItem.objects.create(
            pool=self.exchange_pool,
            prize=self.prize2,
            origin_num=5,
            consumed_num=2,
            exchange_price=200,
            exchange_limit=2,
            exchange_attributes=[
                {'name': 'size', 'range': ['S', 'M', 'L']},
                {'name': 'color', 'range': ['red', 'blue']}
            ],
        )

        self.lottery_item1 = PoolItem.objects.create(
            pool=self.lottery_pool,
            prize=self.prize1,
            origin_num=5,
            consumed_num=0,
            is_big_prize=True,
        )

        self.lottery_item2 = PoolItem.objects.create(
            pool=self.lottery_pool,
            prize=self.prize2,
            origin_num=10,
            consumed_num=0,
            is_big_prize=False,
        )

        self.random_item1 = PoolItem.objects.create(
            pool=self.random_pool,
            prize=self.prize1,
            origin_num=5,
            consumed_num=0,
            is_big_prize=False,
        )

        self.random_item2 = PoolItem.objects.create(
            pool=self.random_pool,
            prize=self.prize2,
            origin_num=3,
            consumed_num=0,
            is_big_prize=True,
        )

        self.random_empty_item = PoolItem.objects.create(
            pool=self.random_pool,
            prize=None,
            origin_num=2,
            consumed_num=0,
            is_empty_prize=True,
        )

        self.client = APIClient()

    def test_list_pools_requires_auth(self):
        """Test that listing pools requires authentication."""
        url = '/api/v2/YQpools/'
        response = self.client.get(url)
        self.assertEqual(response.status_code,
                         http_status.HTTP_401_UNAUTHORIZED)

    def test_get_exchange_pools(self):
        """Test getting exchange pools."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('pools_info', response.data)
        self.assertIsInstance(response.data['pools_info'], list)
        # Should contain our exchange pool
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertIn(self.exchange_pool.id, pool_ids)

    def test_get_lottery_pools(self):
        """Test getting lottery pools."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/lottery/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('pools_info', response.data)
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertIn(self.lottery_pool.id, pool_ids)

    def test_get_random_pools(self):
        """Test getting random pools."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/random/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('pools_info', response.data)
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertIn(self.random_pool.id, pool_ids)

    def test_get_all_pools(self):
        """Test getting all pools at once."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('exchange_pools', response.data)
        self.assertIn('lottery_pools', response.data)
        self.assertIn('random_pools', response.data)
        self.assertIn('pools_info', response.data['exchange_pools'])
        self.assertIn('pools_info', response.data['lottery_pools'])
        self.assertIn('pools_info', response.data['random_pools'])

    def test_get_pool_detail(self):
        """Test getting a specific pool."""
        self.client.force_authenticate(user=self.user)
        url = f'/api/v2/YQpools/{self.exchange_pool.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.exchange_pool.id)
        self.assertEqual(response.data['title'], 'Test Exchange Pool')
        self.assertIn('items', response.data)
        self.assertGreater(len(response.data['items']), 0)

    def test_get_pool_detail_not_found(self):
        """Test getting a non-existent pool."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/99999/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_get_balance(self):
        """Test getting user's YQPoint balance."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/balance/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('YQpoint', response.data)
        self.assertEqual(response.data['YQpoint'], 1000)

    def test_purchase_exchange_success(self):
        """Test successful exchange purchase."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/purchase/'

        initial_balance = self.user.YQpoint
        response = self.client.post(
            url,
            {
                'poolitem_id': self.exchange_item1.id,
                'attributes': {}
            },
            format='json'
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['succeed'])
        self.assertIn('message', response.data)

        # Verify YQPoints were deducted
        self.user.refresh_from_db()
        self.assertEqual(self.user.YQpoint, initial_balance -
                         self.exchange_item1.exchange_price)

        # Verify pool item consumed_num increased
        self.exchange_item1.refresh_from_db()
        self.assertEqual(self.exchange_item1.consumed_num, 1)

        # Verify PoolRecord was created
        self.assertTrue(
            PoolRecord.objects.filter(
                user=self.user,
                pool=self.exchange_pool,
                prize=self.prize1
            ).exists()
        )

    def test_purchase_exchange_with_attributes(self):
        """Test exchange purchase with required attributes."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/purchase/'

        response = self.client.post(
            url,
            {
                'poolitem_id': self.exchange_item2.id,
                'attributes': {
                    'size': 'L',
                    'color': 'red'
                }
            },
            format='json'
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['succeed'])

    def test_purchase_exchange_insufficient_points(self):
        """Test exchange purchase with insufficient YQPoints."""
        self.user.YQpoint = 50  # Less than exchange_price
        self.user.save()

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/purchase/'

        response = self.client.post(
            url,
            {
                'poolitem_id': self.exchange_item1.id,
                'attributes': {}
            },
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('元气值不足', response.data['message'])

    def test_purchase_exchange_sold_out(self):
        """Test exchange purchase when item is sold out."""
        self.exchange_item1.consumed_num = self.exchange_item1.origin_num
        self.exchange_item1.save()

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/purchase/'

        response = self.client.post(
            url,
            {
                'poolitem_id': self.exchange_item1.id,
                'attributes': {}
            },
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('售罄', response.data['message'])

    def test_purchase_exchange_limit_reached(self):
        """Test exchange purchase when limit is reached."""
        # Create a record showing user already exchanged
        PoolRecord.objects.create(
            user=self.user,
            pool=self.exchange_pool,
            prize=self.prize1,
            status=PoolRecord.Status.UN_REDEEM
        )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/purchase/'

        response = self.client.post(
            url,
            {
                'poolitem_id': self.exchange_item1.id,
                'attributes': {}
            },
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('上限', response.data['message'])

    def test_purchase_exchange_missing_attributes(self):
        """Test exchange purchase with missing required attributes."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/purchase/'

        response = self.client.post(
            url,
            {
                'poolitem_id': self.exchange_item2.id,
                'attributes': {
                    'size': 'L'
                    # Missing 'color'
                }
            },
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('兑换信息', response.data['message'])

    def test_purchase_lottery_success(self):
        """Test successful lottery purchase."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/lottery/purchase/'

        initial_balance = self.user.YQpoint
        response = self.client.post(
            url,
            {'pool_id': self.lottery_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['succeed'])
        self.assertIn('抽奖', response.data['message'])

        # Verify YQPoints were deducted
        self.user.refresh_from_db()
        self.assertEqual(self.user.YQpoint, initial_balance -
                         self.lottery_pool.ticket_price)

        # Verify PoolRecord was created with LOTTERING status
        self.assertTrue(
            PoolRecord.objects.filter(
                user=self.user,
                pool=self.lottery_pool,
                status=PoolRecord.Status.LOTTERING
            ).exists()
        )

    def test_purchase_lottery_insufficient_points(self):
        """Test lottery purchase with insufficient YQPoints."""
        self.user.YQpoint = 20  # Less than ticket_price
        self.user.save()

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/lottery/purchase/'

        response = self.client.post(
            url,
            {'pool_id': self.lottery_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])

    def test_purchase_lottery_limit_reached(self):
        """Test lottery purchase when entry limit is reached."""
        # Create records showing user already participated
        for _ in range(self.lottery_pool.entry_time):
            PoolRecord.objects.create(
                user=self.user,
                pool=self.lottery_pool,
                status=PoolRecord.Status.LOTTERING
            )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/lottery/purchase/'

        response = self.client.post(
            url,
            {'pool_id': self.lottery_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('上限', response.data['message'])

    def test_purchase_random_success(self):
        """Test successful random box purchase."""
        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/random/purchase/'

        initial_balance = self.user.YQpoint
        response = self.client.post(
            url,
            {'pool_id': self.random_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['succeed'])
        self.assertIn('effect_code', response.data)
        self.assertIn('prize_id', response.data)
        self.assertIn('compensate_YQPoint', response.data)

        # Verify YQPoints were deducted (account for possible empty box compensation)
        self.user.refresh_from_db()
        expected_balance = initial_balance - self.random_pool.ticket_price + \
            response.data['compensate_YQPoint']
        self.assertEqual(self.user.YQpoint, expected_balance)

        # Verify PoolRecord was created
        self.assertTrue(
            PoolRecord.objects.filter(
                user=self.user,
                pool=self.random_pool
            ).exists()
        )

    def test_purchase_random_empty_box(self):
        """Test random box purchase that results in empty box."""
        # Set all non-empty items to consumed
        self.random_item1.consumed_num = self.random_item1.origin_num
        self.random_item1.save()
        self.random_item2.consumed_num = self.random_item2.origin_num
        self.random_item2.save()

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/random/purchase/'

        initial_balance = self.user.YQpoint
        response = self.client.post(
            url,
            {'pool_id': self.random_pool.id},
            format='json'
        )

        # Should succeed but get empty box
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['succeed'])
        self.assertEqual(response.data['effect_code'], 1)  # Empty box
        self.assertIsNone(response.data['prize_id'])
        # Should have compensation
        self.assertGreaterEqual(response.data['compensate_YQPoint'], 10)
        self.assertLessEqual(response.data['compensate_YQPoint'], 20)

        # Verify compensation was added
        self.user.refresh_from_db()
        expected_balance = initial_balance - self.random_pool.ticket_price + \
            response.data['compensate_YQPoint']
        self.assertEqual(self.user.YQpoint, expected_balance)

    def test_purchase_random_insufficient_points(self):
        """Test random purchase with insufficient YQPoints."""
        self.user.YQpoint = 10  # Less than ticket_price
        self.user.save()

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/random/purchase/'

        response = self.client.post(
            url,
            {'pool_id': self.random_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])

    def test_purchase_random_limit_reached(self):
        """Test random purchase when entry limit is reached."""
        # Create records showing user already participated
        for _ in range(self.random_pool.entry_time):
            PoolRecord.objects.create(
                user=self.user,
                pool=self.random_pool,
                status=PoolRecord.Status.UN_REDEEM,
                prize=self.prize1
            )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/random/purchase/'

        response = self.client.post(
            url,
            {'pool_id': self.random_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('上限', response.data['message'])

    def test_purchase_random_sold_out(self):
        """Test random purchase when pool is sold out."""
        # Consume all items
        total_capacity = sum([
            self.random_item1.origin_num,
            self.random_item2.origin_num,
            self.random_empty_item.origin_num
        ])

        # Create records to fill capacity using different users to avoid hitting entry_time limit
        # Create additional test users
        for i in range(total_capacity):
            other_user = User.objects.create_user(
                username=f'testuser_soldout_{i}',
                password='testpass123',
                name=f'U{i:02d}',  # Format as U00, U01, etc. (max 4 chars)
                usertype=User.Type.PERSON,
            )
            NaturalPerson.objects.create(other_user, name=f'U{i:02d}')
            PoolRecord.objects.create(
                user=other_user,
                pool=self.random_pool,
                status=PoolRecord.Status.UN_REDEEM,
                prize=self.prize1
            )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/random/purchase/'

        response = self.client.post(
            url,
            {'pool_id': self.random_pool.id},
            format='json'
        )

        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['succeed'])
        self.assertIn('售罄', response.data['message'])

    def test_pool_expired_not_shown(self):
        """Test that expired pools are not shown."""
        # Create an expired pool
        expired_pool = Pool.objects.create(
            title='Expired Pool',
            type=Pool.Type.EXCHANGE,
            start=timezone.now() - timedelta(days=3),
            end=timezone.now() - timedelta(days=2),  # Ended 2 days ago
        )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertNotIn(expired_pool.id, pool_ids)

    def test_pool_not_started_not_shown(self):
        """Test that pools that haven't started are not shown."""
        # Create a future pool
        future_pool = Pool.objects.create(
            title='Future Pool',
            type=Pool.Type.EXCHANGE,
            start=timezone.now() + timedelta(days=1),
            end=timezone.now() + timedelta(days=2),
        )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertNotIn(future_pool.id, pool_ids)

    def test_pool_with_activity_requires_participation(self):
        """Test that pools with activities require user participation."""
        from app.models import Activity, Participation

        # Create an activity
        activity = Activity.objects.create(
            title='Test Activity',
            introduction='Test',
            location='Test Location',
            organization_id=self.organization,
            examine_teacher=self.natural_person,
            start=timezone.now() - timedelta(days=2),
            end=timezone.now() - timedelta(days=1),
            status=Activity.Status.END,
        )

        # Create a pool linked to activity
        activity_pool = Pool.objects.create(
            title='Activity Pool',
            type=Pool.Type.EXCHANGE,
            start=timezone.now() - timedelta(days=1),
            end=timezone.now() + timedelta(days=1),
            activity=activity,
        )

        PoolItem.objects.create(
            pool=activity_pool,
            prize=self.prize1,
            origin_num=10,
            exchange_price=50,
        )

        self.client.force_authenticate(user=self.user)
        url = '/api/v2/YQpools/exchange/'
        response = self.client.get(url)

        # Pool should not be shown because user didn't participate
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertNotIn(activity_pool.id, pool_ids)

        # Now create participation
        Participation.objects.create(
            activity=activity,
            person=self.natural_person,
            status=Participation.AttendStatus.ATTENDED,
        )

        # Refresh and check again
        response = self.client.get(url)
        pool_ids = [p['id'] for p in response.data['pools_info']]
        self.assertIn(activity_pool.id, pool_ids)

    def test_exchange_pool_items_sorted_by_remain(self):
        """Test that exchange pool items are sorted by remaining quantity."""
        self.client.force_authenticate(user=self.user)
        url = f'/api/v2/YQpools/{self.exchange_pool.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        items = response.data['items']

        # Verify items are sorted by remain_num (descending)
        if len(items) > 1:
            for i in range(len(items) - 1):
                remain1 = items[i].get(
                    'remain_num', items[i]['origin_num'] - items[i]['consumed_num'])
                remain2 = items[i + 1].get('remain_num', items[i + 1]
                                           ['origin_num'] - items[i + 1]['consumed_num'])
                self.assertGreaterEqual(remain1, remain2)

    def test_lottery_pool_shows_results_when_ended(self):
        """Test that ended lottery pools show results."""
        # End the lottery pool
        self.lottery_pool.end = timezone.now() - timedelta(hours=12)
        self.lottery_pool.save()

        # Create some lottery records and run lottery
        PoolRecord.objects.create(
            user=self.user,
            pool=self.lottery_pool,
            status=PoolRecord.Status.LOTTERING
        )
        run_lottery(self.lottery_pool.id)

        self.client.force_authenticate(user=self.user)
        url = f'/api/v2/YQpools/{self.lottery_pool.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        # Should have results if status is 1 (ended)
        if response.data.get('status') == 1:
            self.assertIn('results', response.data)

    def test_random_pool_shows_probability(self):
        """Test that random pools show probability for each item."""
        self.client.force_authenticate(user=self.user)
        url = f'/api/v2/YQpools/{self.random_pool.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        items = response.data['items']

        # Verify items have probability field
        for item in items:
            self.assertIn('probability', item)
            self.assertGreaterEqual(item['probability'], 0)
            self.assertLessEqual(item['probability'], 100)
