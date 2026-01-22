"""
Tests for appointment API.
"""
from rest_framework.test import APITestCase, APIClient
from rest_framework import status as http_status
from django.contrib.auth import get_user_model
from Appointment.models import Participant

User = get_user_model()


class AppointAPITestCase(APITestCase):
    """Base test case for appointment API tests."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            name='Test User'
        )
        # Create participant for the user
        self.participant = Participant.objects.create(Sid=self.user)
        # Authenticate
        self.client.force_authenticate(user=self.user)

    def test_account_endpoint(self):
        """Test account endpoint returns user appointment information."""
        response = self.client.get('/api/v2/appoint/account/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('user_info', response.data)
        self.assertIn('appoint_list_future', response.data)
        self.assertIn('appoint_list_past', response.data)

    def test_credit_endpoint(self):
        """Test credit endpoint returns violation records."""
        response = self.client.get('/api/v2/appoint/credit/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('user_info', response.data)
        self.assertIn('vio_list', response.data)

    def test_index_endpoint(self):
        """Test index endpoint returns room status and announcements."""
        response = self.client.get('/api/v2/appoint/index/')
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

    def test_arrange_time_endpoint_requires_rid(self):
        """Test arrange_time endpoint requires Rid parameter."""
        response = self.client.get('/api/v2/appoint/arrange-time/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    def test_arrange_talk_room_endpoint_requires_params(self):
        """Test arrange_talk_room endpoint requires date parameters."""
        response = self.client.get('/api/v2/appoint/arrange-talk-room/')
        self.assertEqual(response.status_code,
                         http_status.HTTP_400_BAD_REQUEST)

    # TODO: Add tests for appointment creation (valid and invalid)
