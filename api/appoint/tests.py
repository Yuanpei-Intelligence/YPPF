"""
Tests for appointment API.
"""
from rest_framework.test import APITestCase, APIClient
from rest_framework import status as http_status
from django.contrib.auth import get_user_model
from Appointment.models import Participant
from generic.models import User
from app.models import NaturalPerson, Organization, OrganizationType


class AppointAPITestCasePerson(APITestCase):
    """Base test case for appointment API tests."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            name='Test User',
            utype=User.Type.PERSON
        )
        self.natural_person = NaturalPerson.objects.create(
            user=self.user, name='Test User')
        # Create participant for the user
        self.participant = Participant.objects.create(Sid=self.user)
        # Authenticate
        self.client.force_authenticate(user=self.user)

    def test_my_appointments_endpoint(self):
        """Test my-appointments endpoint returns user appointment information."""
        response = self.client.get('/api/v2/appoint/my-appointments/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('user_info', response.data)
        self.assertIn('appoint_list_future', response.data)
        self.assertIn('appoint_list_past', response.data)

    def test_my_violations_endpoint(self):
        """Test my-violations endpoint returns violation records."""
        response = self.client.get('/api/v2/appoint/my-violations/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('user_info', response.data)
        self.assertIn('vio_list', response.data)

    def test_status_endpoint(self):
        """Test status endpoint returns room status and announcements."""
        response = self.client.get('/api/v2/appoint/status/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('function_room_list', response.data)
        self.assertIn('talk_room_list', response.data)
        self.assertIn('russian_room_list', response.data)

    def test_agreement_get_endpoint(self):
        """Test agreement GET endpoint."""
        response = self.client.get('/api/v2/appoint/agreement/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('agree_time', response.data)

    def test_agreement_post_endpoint(self):
        """Test agreement POST endpoint for signing."""
        response = self.client.post('/api/v2/appoint/agreement/', {
            'type': 'confirm'
        })
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('message', response.data)

    def test_arrange_by_room_endpoint_requires_rid(self):
        """Test arrange-by-room endpoint requires Rid parameter."""
        response = self.client.get('/api/v2/appoint/arrange-by-room/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_arrange_talk_room_by_time_endpoint_requires_params(self):
        """Test arrange-talk-room-by-time endpoint requires date parameters."""
        response = self.client.get(
            '/api/v2/appoint/arrange-talk-room-by-time/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_search_users_endpoint(self):
        """Test search-users endpoint returns matching users."""
        # Create another user to search for
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
            name='Other User'
        )
        Participant.objects.create(Sid=other_user, hidden=False)

        response = self.client.get(
            '/api/v2/appoint/search-users/', {'query': 'Other'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        # Should find the other user
        if len(response.data) > 0:
            self.assertIn('name', response.data[0])

    def test_search_users_endpoint_empty_query(self):
        """Test search-users endpoint with empty query."""
        response = self.client.get('/api/v2/appoint/search-users/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_search_users_endpoint_excludes_current_user(self):
        """Test search-users endpoint excludes current user from results."""
        response = self.client.get(
            '/api/v2/appoint/search-users/', {'query': 'Test'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        # Current user should not be in results
        for user in response.data:
            self.assertNotEqual(user.get('id'), self.user.id)

    def test_search_users_endpoint_respects_limit(self):
        """Test search-users endpoint respects limit parameter."""
        # Create multiple users
        for i in range(5):
            u = User.objects.create_user(
                username=f'user{i}',
                password='testpass123',
                name=f'User {i}'
            )
            Participant.objects.create(Sid=u, hidden=False)

        response = self.client.get(
            '/api/v2/appoint/search-users/', {'query': 'User', 'limit': 2})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertLessEqual(len(response.data), 2)

    def test_checkout_get_endpoint_requires_rid(self):
        """Test checkout GET endpoint requires Rid parameter."""
        response = self.client.get('/api/v2/appoint/checkout/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_cancel_appointment_requires_auth(self):
        """Test cancel endpoint requires authentication."""
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/v2/appoint/appointments/cancel/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_401_UNAUTHORIZED)

    def test_renew_longterm_requires_auth(self):
        """Test renew-longterm endpoint requires authentication."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            '/api/v2/appoint/appointments/renew-longterm/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_401_UNAUTHORIZED)


class AppointAPITestCaseOrg(APITestCase):
    """Base test case for appointment API tests."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            name='Test User',
            utype=User.Type.ORG
        )
        self.participant = Participant.objects.create(Sid=self.user)
        self.organization_type = OrganizationType.objects.create(
            otype_id=1, otype_name='Test Organization Type')
        self.organization = Organization.objects.create(
            organization_id=self.user, oname='Test Organization', otype=OrganizationType.objects.get(otype_id=1))
        # Authenticate
        self.client.force_authenticate(user=self.user)

    def test_my_appointments_endpoint(self):
        """Test my-appointments endpoint returns user appointment information."""
        response = self.client.get('/api/v2/appoint/my-appointments/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('user_info', response.data)
        self.assertIn('appoint_list_future', response.data)
        self.assertIn('appoint_list_past', response.data)

    def test_my_violations_endpoint(self):
        """Test my-violations endpoint returns violation records."""
        response = self.client.get('/api/v2/appoint/my-violations/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('user_info', response.data)
        self.assertIn('vio_list', response.data)

    def test_status_endpoint(self):
        """Test status endpoint returns room status and announcements."""
        response = self.client.get('/api/v2/appoint/status/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('function_room_list', response.data)
        self.assertIn('talk_room_list', response.data)
        self.assertIn('russian_room_list', response.data)

    def test_agreement_get_endpoint(self):
        """Test agreement GET endpoint."""
        response = self.client.get('/api/v2/appoint/agreement/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('agree_time', response.data)

    def test_agreement_post_endpoint(self):
        """Test agreement POST endpoint for signing."""
        response = self.client.post('/api/v2/appoint/agreement/', {
            'type': 'confirm'
        })
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('message', response.data)

    def test_arrange_by_room_endpoint_requires_rid(self):
        """Test arrange-by-room endpoint requires Rid parameter."""
        response = self.client.get('/api/v2/appoint/arrange-by-room/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_arrange_talk_room_by_time_endpoint_requires_params(self):
        """Test arrange-talk-room-by-time endpoint requires date parameters."""
        response = self.client.get(
            '/api/v2/appoint/arrange-talk-room-by-time/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_search_users_endpoint(self):
        """Test search-users endpoint returns matching users."""
        # Create another user to search for
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
            name='Other User'
        )
        Participant.objects.create(Sid=other_user, hidden=False)

        response = self.client.get(
            '/api/v2/appoint/search-users/', {'query': 'Other'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        # Should find the other user
        if len(response.data) > 0:
            self.assertIn('name', response.data[0])

    def test_search_users_endpoint_empty_query(self):
        """Test search-users endpoint with empty query."""
        response = self.client.get('/api/v2/appoint/search-users/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_search_users_endpoint_excludes_current_user(self):
        """Test search-users endpoint excludes current user from results."""
        response = self.client.get(
            '/api/v2/appoint/search-users/', {'query': 'Test'})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        # Current user should not be in results
        for user in response.data:
            self.assertNotEqual(user.get('id'), self.user.id)

    def test_search_users_endpoint_respects_limit(self):
        """Test search-users endpoint respects limit parameter."""
        # Create multiple users
        for i in range(5):
            u = User.objects.create_user(
                username=f'user{i}',
                password='testpass123',
                name=f'User {i}'
            )
            Participant.objects.create(Sid=u, hidden=False)

        response = self.client.get(
            '/api/v2/appoint/search-users/', {'query': 'User', 'limit': 2})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertLessEqual(len(response.data), 2)

    def test_checkout_get_endpoint_requires_rid(self):
        """Test checkout GET endpoint requires Rid parameter."""
        response = self.client.get('/api/v2/appoint/checkout/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_cancel_appointment_requires_auth(self):
        """Test cancel endpoint requires authentication."""
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/v2/appoint/appointments/cancel/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_401_UNAUTHORIZED)

    def test_renew_longterm_requires_auth(self):
        """Test renew-longterm endpoint requires authentication."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            '/api/v2/appoint/appointments/renew-longterm/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_401_UNAUTHORIZED)
