"""Tests for activity API."""

from datetime import datetime, timedelta

from django.test import SimpleTestCase
from django.urls import resolve
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from app.models import (
    Activity,
    NaturalPerson,
    Organization,
    OrganizationType,
    Participation,
)
from generic.models import User
from api.activity.views import ActivityViewSet
from api.activity.serializers import (
    ActivityActionResultSerializer,
    ActivityCheckinRequestSerializer,
    ActivityDetailSerializer,
    ActivitySummarySerializer,
    ActivityHomepageSerializer,
    TodayActivitySerializer,
    SignupActivitySerializer,
)


class ActivityURLTestCase(SimpleTestCase):
    """Test URL routing for activity API."""

    def test_overview_url_resolves(self):
        """Test overview URL resolves correctly."""
        url = '/api/v2/activity/overview/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, ActivityViewSet)
        self.assertEqual(resolver.func.actions['get'], 'overview')

    def test_signup_url_resolves(self):
        """Test signup URL resolves to both signup methods."""
        url = '/api/v2/activity/1/signup/'
        resolver = resolve(url)
        self.assertEqual(resolver.func.cls, ActivityViewSet)
        self.assertEqual(resolver.func.actions['post'], 'signup')
        self.assertEqual(resolver.func.actions['delete'], 'signup')


class SerializerFieldsTestCase(SimpleTestCase):
    """Test serializer field definitions."""

    def test_activity_summary_serializer_fields(self):
        """Test ActivitySummarySerializer has required fields."""
        serializer = ActivitySummarySerializer()
        expected_fields = [
            'id',
            'title',
            'organization_id',
            'organization_name',
            'start',
            'end',
            'location',
            'introduction',
            'status',
            'status_display',
            'need_apply',
            'apply_end',
            'bidding',
            'need_checkin',
            'inner',
            'capacity',
            'current_participants',
            'url',
            'category',
            'category_display',
            'has_tag',
            'popular_level',
        ]
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_activity_detail_serializer_fields(self):
        """Test activity detail adds the current user's signup status."""
        serializer = ActivityDetailSerializer()
        expected_fields = set(ActivitySummarySerializer().fields.keys()) | {
            'participation_status',
        }
        self.assertEqual(set(serializer.fields.keys()), expected_fields)

    def test_activity_action_result_serializer_fields(self):
        """Test signup result exposes the updated activity state."""
        serializer = ActivityActionResultSerializer()
        expected_fields = {
            'message',
            'participation_status',
            'current_participants',
        }
        self.assertEqual(set(serializer.fields.keys()), expected_fields)

    def test_activity_checkin_request_serializer_fields(self):
        """Test check-in input is validated by a concrete serializer."""
        serializer = ActivityCheckinRequestSerializer()
        self.assertEqual(set(serializer.fields.keys()), {'aid'})

    def test_today_activity_serializer_fields(self):
        """Test TodayActivitySerializer has required fields."""
        serializer = TodayActivitySerializer()
        expected_fields = ['activity', 'start_time']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_signup_activity_serializer_fields(self):
        """Test SignupActivitySerializer has required fields."""
        serializer = SignupActivitySerializer()
        expected_fields = ['activity', 'apply_end', 'hours_until_deadline']
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))

    def test_activity_homepage_serializer_fields(self):
        """Test ActivityHomepageSerializer has required fields."""
        serializer = ActivityHomepageSerializer()
        expected_fields = [
            'recent_activities',
            'today_activities',
            'newly_released_activities',
            'prepare_times',
            'signup_activities',
        ]
        self.assertEqual(set(serializer.fields.keys()), set(expected_fields))


class ViewSetConfigTestCase(SimpleTestCase):
    """Test ViewSet configuration."""

    def test_viewset_has_permission_classes(self):
        """Test ActivityViewSet has permission classes."""
        from rest_framework.permissions import IsAuthenticated
        self.assertIn(IsAuthenticated, ActivityViewSet.permission_classes)

    def test_viewset_has_authentication_classes(self):
        """Test ActivityViewSet has authentication classes."""
        from api.authentication import WxJWTAuthentication
        self.assertIn(WxJWTAuthentication,
                      ActivityViewSet.authentication_classes)

    def test_viewset_has_overview_action(self):
        """Test ActivityViewSet has overview action."""
        self.assertTrue(hasattr(ActivityViewSet, 'overview'))
        self.assertTrue(callable(getattr(ActivityViewSet, 'overview')))


class ActivitySignupAPITestCase(APITestCase):
    """Test signup, withdrawal, detail status, and check-in flows."""

    def setUp(self):
        """Create a personal user, organization, and open activity."""
        self.client = APIClient()
        self.person_user = User.objects.create_user(
            username='signup_person',
            name='报名同学',
            usertype=User.Type.PERSON,
            password='testpass',
        )
        self.person = NaturalPerson.objects.create(
            self.person_user,
            name='报名同学',
        )
        self.teacher_user = User.objects.create_user(
            username='signup_teacher',
            name='审核老师',
            usertype=User.Type.TEACHER,
            password='testpass',
        )
        self.teacher = NaturalPerson.objects.create(
            self.teacher_user,
            name='审核老师',
        )
        self.org_type = OrganizationType.objects.create(
            otype_id=101,
            otype_name='活动小组类型',
            incharge=self.teacher,
            job_name_list=['负责人', '成员'],
        )
        self.org_user = User.objects.create_user(
            username='signup_org',
            name='活动小组',
            usertype=User.Type.ORG,
            password='testpass',
        )
        self.org = Organization.objects.create(
            organization_id=self.org_user,
            oname='活动小组',
            otype=self.org_type,
        )
        now = datetime.now()
        self.activity = Activity.objects.create(
            title='新生之旅测试活动',
            organization_id=self.org,
            examine_teacher=self.teacher,
            need_apply=True,
            need_checkin=True,
            status=Activity.Status.APPLYING,
            apply_end=now + timedelta(hours=2),
            start=now + timedelta(hours=3),
            end=now + timedelta(hours=5),
            capacity=2,
            current_participants=0,
        )

    def signup_url(self):
        """Return the signup endpoint for the test activity."""
        return f'/api/v2/activity/{self.activity.id}/signup/'

    def detail_url(self):
        """Return the detail endpoint for the test activity."""
        return f'/api/v2/activity/{self.activity.id}/'

    def assert_api_error(self, response, expected_status, expected_code):
        """Assert the canonical mini-program API error envelope."""
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(
            set(response.data.keys()),
            {'code', 'message', 'errors'},
        )
        self.assertEqual(response.data['code'], expected_code)
        self.assertIsInstance(response.data['message'], str)
        self.assertIsInstance(response.data['errors'], dict)

    def test_detail_returns_null_participation_before_signup(self):
        """A person who has not signed up sees a null status."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['participation_status'])

    def test_signup_requires_authentication(self):
        """An anonymous signup request returns canonical 401."""
        response = self.client.post(self.signup_url(), format='json')
        self.assert_api_error(
            response,
            status.HTTP_401_UNAUTHORIZED,
            'not_authenticated',
        )

    def test_signup_requires_person_account(self):
        """An organization account cannot sign up for an activity."""
        self.client.force_authenticate(user=self.org_user)
        response = self.client.post(self.signup_url(), format='json')
        self.assert_api_error(
            response,
            status.HTTP_403_FORBIDDEN,
            'permission_denied',
        )

    def test_signup_creates_participation_and_updates_count(self):
        """A successful signup creates the record and increments capacity."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(self.signup_url(), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['participation_status'],
            Participation.AttendStatus.APPLYSUCCESS,
        )
        self.assertEqual(response.data['current_participants'], 1)
        participation = Participation.objects.get(
            activity=self.activity,
            person=self.person,
        )
        self.assertEqual(
            participation.status,
            Participation.AttendStatus.APPLYSUCCESS,
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.current_participants, 1)

    def test_detail_returns_participation_status_after_signup(self):
        """Activity detail reflects the current person's signup state."""
        Participation.objects.create(
            activity=self.activity,
            person=self.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        self.client.force_authenticate(user=self.person_user)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['participation_status'],
            Participation.AttendStatus.APPLYSUCCESS,
        )

    def test_detail_does_not_expose_another_persons_status(self):
        """Activity detail only reports the authenticated person's status."""
        other_user = User.objects.create_user(
            username='other_signup_person',
            name='其他报名同学',
            usertype=User.Type.PERSON,
            password='testpass',
        )
        other_person = NaturalPerson.objects.create(
            other_user,
            name='其他报名同学',
        )
        Participation.objects.create(
            activity=self.activity,
            person=other_person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        self.client.force_authenticate(user=self.person_user)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['participation_status'])

    def test_inactive_person_cannot_signup(self):
        """Signup reloads and locks business-active account state."""
        self.client.force_authenticate(user=self.person_user)
        User.objects.filter(pk=self.person_user.pk).update(active=False)

        self.assertTrue(self.person_user.active)

        response = self.client.post(self.signup_url(), format='json')

        self.assert_api_error(
            response,
            status.HTTP_403_FORBIDDEN,
            'permission_denied',
        )
        self.assertFalse(
            Participation.objects.filter(
                activity=self.activity,
                person=self.person,
            ).exists(),
        )

    def test_duplicate_signup_returns_conflict_without_incrementing(self):
        """Submitting signup twice does not consume another place."""
        Participation.objects.create(
            activity=self.activity,
            person=self.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        self.activity.current_participants = 1
        self.activity.save(update_fields=['current_participants'])
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(self.signup_url(), format='json')

        self.assert_api_error(
            response,
            status.HTTP_409_CONFLICT,
            'conflict',
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.current_participants, 1)

    def test_signup_full_activity_returns_conflict(self):
        """A full first-come-first-served activity rejects signup."""
        self.activity.current_participants = self.activity.capacity
        self.activity.save(update_fields=['current_participants'])
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(self.signup_url(), format='json')

        self.assert_api_error(
            response,
            status.HTTP_409_CONFLICT,
            'conflict',
        )
        self.assertFalse(
            Participation.objects.filter(
                activity=self.activity,
                person=self.person,
            ).exists(),
        )

    def test_signup_closed_activity_returns_conflict(self):
        """Signup is rejected after the activity leaves APPLYING state."""
        self.activity.status = Activity.Status.WAITING
        self.activity.save(update_fields=['status'])
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(self.signup_url(), format='json')

        self.assert_api_error(
            response,
            status.HTTP_409_CONFLICT,
            'conflict',
        )

    def test_signup_unknown_activity_returns_not_found(self):
        """Signup for a missing activity returns canonical 404."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            '/api/v2/activity/999999/signup/',
            format='json',
        )
        self.assert_api_error(
            response,
            status.HTTP_404_NOT_FOUND,
            'not_found',
        )

    def test_inner_activity_rejects_nonmember(self):
        """A person outside the organizer cannot join an inner activity."""
        self.activity.inner = True
        self.activity.save(update_fields=['inner'])
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(self.signup_url(), format='json')

        self.assert_api_error(
            response,
            status.HTTP_403_FORBIDDEN,
            'permission_denied',
        )

    def test_bidding_signup_creates_pending_application(self):
        """A bidding activity records the signup as a pending application."""
        self.activity.bidding = True
        self.activity.save(update_fields=['bidding'])
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(self.signup_url(), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['participation_status'],
            Participation.AttendStatus.APPLYING,
        )
        self.assertIn('等待报名结果', response.data['message'])

    def test_withdraw_updates_participation_and_count(self):
        """Deleting signup cancels the record and releases the place."""
        participation = Participation.objects.create(
            activity=self.activity,
            person=self.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        self.activity.current_participants = 1
        self.activity.save(update_fields=['current_participants'])
        self.client.force_authenticate(user=self.person_user)

        response = self.client.delete(self.signup_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['participation_status'],
            Participation.AttendStatus.CANCELED,
        )
        self.assertEqual(response.data['current_participants'], 0)
        participation.refresh_from_db()
        self.assertEqual(
            participation.status,
            Participation.AttendStatus.CANCELED,
        )

    def test_withdraw_without_signup_returns_conflict(self):
        """A person cannot withdraw from an activity they did not join."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.delete(self.signup_url())
        self.assert_api_error(
            response,
            status.HTTP_409_CONFLICT,
            'conflict',
        )

    def test_withdraw_after_activity_starts_returns_conflict(self):
        """Signup cannot be withdrawn after the activity starts."""
        self.activity.status = Activity.Status.PROGRESSING
        self.activity.save(update_fields=['status'])
        Participation.objects.create(
            activity=self.activity,
            person=self.person,
            status=Participation.AttendStatus.UNATTENDED,
        )
        self.client.force_authenticate(user=self.person_user)

        response = self.client.delete(self.signup_url())

        self.assert_api_error(
            response,
            status.HTTP_409_CONFLICT,
            'conflict',
        )

    def test_checkin_after_signup_updates_participation(self):
        """A registered person can check in during the allowed window."""
        self.activity.status = Activity.Status.WAITING
        self.activity.start = datetime.now() + timedelta(minutes=30)
        self.activity.save(update_fields=['status', 'start'])
        participation = Participation.objects.create(
            activity=self.activity,
            person=self.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(
            '/api/v2/activity/checkin/',
            {'aid': self.activity.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        participation.refresh_from_db()
        self.assertEqual(
            participation.status,
            Participation.AttendStatus.ATTENDED,
        )

    def test_checkin_requires_activity_id(self):
        """Missing check-in activity ID returns a field validation error."""
        self.client.force_authenticate(user=self.person_user)
        response = self.client.post(
            '/api/v2/activity/checkin/',
            {},
            format='json',
        )
        self.assert_api_error(
            response,
            status.HTTP_400_BAD_REQUEST,
            'validation_error',
        )
        self.assertIn('aid', response.data['errors'])

    def test_checkin_rejects_activity_without_checkin(self):
        """The API cannot check users into an activity that needs no check-in."""
        self.activity.status = Activity.Status.WAITING
        self.activity.start = datetime.now() + timedelta(minutes=30)
        self.activity.need_checkin = False
        self.activity.save(update_fields=['status', 'start', 'need_checkin'])
        Participation.objects.create(
            activity=self.activity,
            person=self.person,
            status=Participation.AttendStatus.APPLYSUCCESS,
        )
        self.client.force_authenticate(user=self.person_user)

        response = self.client.post(
            '/api/v2/activity/checkin/',
            {'aid': self.activity.id},
            format='json',
        )

        self.assert_api_error(
            response,
            status.HTTP_400_BAD_REQUEST,
            'validation_error',
        )
