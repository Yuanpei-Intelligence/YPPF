"""
Tests for notification API.
"""
from datetime import datetime
from unittest import mock

from django.urls import reverse
from rest_framework import status as http_status
from rest_framework.test import APITestCase, APIClient

from app.models import Notification
from generic.models import User
from utils.global_messages import wrong


class NotificationAPITestCase(APITestCase):
    """Test cases for Notification API endpoints."""

    def setUp(self):
        """Set up test data."""
        # Create test users
        self.user1 = User.objects.create_user(
            username='testuser1',
            password='testpass123',
            name='Test User 1',
            usertype=User.Type.STUDENT
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            password='testpass123',
            name='Test User 2',
            usertype=User.Type.STUDENT
        )
        
        self.client = APIClient()
        
        # Create test notifications
        self.notification1 = Notification.objects.create(
            receiver=self.user1,
            sender=self.user2,
            typename=Notification.Type.NEEDREAD,
            title="Test Notification 1",
            content="This is a test notification",
            status=Notification.Status.UNDONE,
            URL="http://example.com"
        )
        
        self.notification2 = Notification.objects.create(
            receiver=self.user1,
            sender=self.user2,
            typename=Notification.Type.NEEDDO,
            title="Test Notification 2",
            content="This is another test notification",
            status=Notification.Status.DONE,
            finish_time=datetime.now()
        )
        
        self.notification3 = Notification.objects.create(
            receiver=self.user2,
            sender=self.user1,
            typename=Notification.Type.NEEDREAD,
            title="Test Notification 3",
            content="Notification for user2",
            status=Notification.Status.UNDONE
        )

    def assert_error(self, response, expected_status, expected_code):
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(set(response.data), {"code", "message", "errors"})
        self.assertEqual(response.data["code"], expected_code)
        self.assertIsInstance(response.data["message"], str)
        self.assertIsInstance(response.data["errors"], dict)

    def test_list_notifications_unauthenticated(self):
        """Test that unauthenticated users cannot list notifications."""
        url = reverse('api:notification:notification-list')
        response = self.client.get(url)
        self.assert_error(
            response,
            http_status.HTTP_401_UNAUTHORIZED,
            "invalid_token",
        )
        self.assertEqual(response.data["errors"], {})

    def test_list_notifications_authenticated(self):
        """Test listing notifications for authenticated user."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)  # user1 has 2 notifications
        
        # Verify all notifications belong to user1
        for notification in response.data:
            self.assertIn(notification['id'], [self.notification1.id, self.notification2.id])

    def test_list_notifications_filter_by_status(self):
        """Test filtering notifications by status."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-list')
        
        # Filter by UNDONE status
        response = self.client.get(url, {'status': Notification.Status.UNDONE})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.notification1.id)
        
        # Filter by DONE status
        response = self.client.get(url, {'status': Notification.Status.DONE})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.notification2.id)

    def test_list_notifications_filter_by_type(self):
        """Test filtering notifications by type."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-list')
        
        # Filter by NEEDREAD type
        response = self.client.get(url, {'typename': Notification.Type.NEEDREAD})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.notification1.id)
        
        # Filter by NEEDDO type
        response = self.client.get(url, {'typename': Notification.Type.NEEDDO})
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.notification2.id)

    def test_list_notifications_ordering(self):
        """Test ordering of notifications."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-list')
        
        # Default ordering (should be -start_time)
        response = self.client.get(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        
        # Verify ordering is by -start_time (newest first)
        if len(response.data) > 1:
            for i in range(len(response.data) - 1):
                time1 = datetime.fromisoformat(response.data[i]['start_time'].replace(' ', 'T'))
                time2 = datetime.fromisoformat(response.data[i + 1]['start_time'].replace(' ', 'T'))
                self.assertGreaterEqual(time1, time2)

    def test_list_notifications_rejects_invalid_query(self):
        """Invalid filters use the standardized field-error contract."""
        self.client.force_authenticate(user=self.user1)
        url = reverse("api:notification:notification-list")

        response = self.client.get(
            url,
            {"status": 999, "ordering": "receiver__password"},
        )

        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "validation_error",
        )
        self.assertEqual(
            response.data["errors"]["status"][0]["code"],
            "invalid_choice",
        )
        self.assertEqual(
            response.data["errors"]["ordering"][0]["code"],
            "invalid_choice",
        )

    def test_retrieve_notification(self):
        """Test retrieving a specific notification."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-detail', kwargs={'pk': self.notification1.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.notification1.id)
        self.assertEqual(response.data['title'], "Test Notification 1")
        self.assertEqual(response.data['content'], "This is a test notification")

    def test_retrieve_notification_forbidden(self):
        """Test that users cannot retrieve notifications of other users."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-detail', kwargs={'pk': self.notification3.id})
        response = self.client.get(url)
        
        self.assert_error(
            response,
            http_status.HTTP_404_NOT_FOUND,
            "not_found",
        )
        self.assertEqual(response.data["message"], "通知不存在。")

    def test_retrieve_notification_not_found(self):
        """Test retrieving a non-existent notification."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-detail', kwargs={'pk': 99999})
        response = self.client.get(url)
        
        self.assert_error(
            response,
            http_status.HTTP_404_NOT_FOUND,
            "not_found",
        )

    def test_update_notification_status(self):
        """Test updating notification status."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-update-status', 
                     kwargs={'pk': self.notification1.id})
        
        # Update to DONE
        response = self.client.patch(url, {'status': Notification.Status.DONE}, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Notification.Status.DONE)
        
        # Verify in database
        self.notification1.refresh_from_db()
        self.assertEqual(self.notification1.status, Notification.Status.DONE)
        self.assertIsNotNone(self.notification1.finish_time)

    def test_update_notification_status_to_delete(self):
        """Test updating notification status to DELETE."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-update-status', 
                     kwargs={'pk': self.notification1.id})
        
        response = self.client.patch(url, {'status': Notification.Status.DELETE}, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Notification.Status.DELETE)

    def test_update_notification_status_invalid(self):
        """Test updating notification with invalid status."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-update-status', 
                     kwargs={'pk': self.notification1.id})
        
        response = self.client.patch(url, {'status': 999}, format='json')
        self.assert_error(
            response,
            http_status.HTTP_400_BAD_REQUEST,
            "validation_error",
        )
        self.assertEqual(
            response.data["errors"]["status"][0]["code"],
            "invalid_choice",
        )

    def test_update_notification_status_conflict(self):
        """A failed domain transition becomes a stable 409 response."""
        self.client.force_authenticate(user=self.user1)
        url = reverse(
            "api:notification:notification-update-status",
            kwargs={"pk": self.notification1.id},
        )

        with mock.patch(
            "api.notification.views.notification_status_change",
            return_value=wrong("legacy internal detail"),
        ):
            response = self.client.patch(
                url,
                {"status": Notification.Status.DONE},
                format="json",
            )

        self.assert_error(
            response,
            http_status.HTTP_409_CONFLICT,
            "notification.state_conflict",
        )
        self.assertNotIn("legacy", response.data["message"])

    def test_deleted_notification_is_hidden(self):
        """Deleted notifications are not visible or mutable through the API."""
        self.notification1.status = Notification.Status.DELETE
        self.notification1.save(update_fields=["status"])
        self.client.force_authenticate(user=self.user1)
        url = reverse(
            "api:notification:notification-detail",
            kwargs={"pk": self.notification1.id},
        )

        response = self.client.get(url)

        self.assert_error(
            response,
            http_status.HTTP_404_NOT_FOUND,
            "not_found",
        )

    def test_toggle_notification_status(self):
        """Test toggling notification status."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-toggle-status', 
                     kwargs={'pk': self.notification1.id})
        
        # Toggle from UNDONE to DONE
        response = self.client.post(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Notification.Status.DONE)
        
        # Toggle back to UNDONE
        response = self.client.post(url)
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Notification.Status.UNDONE)

    def test_mark_all_read(self):
        """Test marking all notifications as read."""
        self.client.force_authenticate(user=self.user1)
        
        # Verify we have unread notifications
        self.assertEqual(
            Notification.objects.filter(
                receiver=self.user1,
                status=Notification.Status.UNDONE
            ).count(),
            1
        )
        
        url = reverse('api:notification:notification-mark-all-read')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data["message"], "已将 1 条通知标记为已读。")
        
        # Verify all NEEDREAD notifications are now DONE
        self.assertEqual(
            Notification.objects.filter(
                receiver=self.user1,
                typename=Notification.Type.NEEDREAD,
                status=Notification.Status.UNDONE
            ).count(),
            0
        )

    def test_delete_all_read(self):
        """Test deleting all read notifications."""
        self.client.force_authenticate(user=self.user1)
        
        # Mark a notification as done first
        self.notification1.status = Notification.Status.DONE
        self.notification1.finish_time = datetime.now()
        self.notification1.save()
        
        # Verify we have read NEEDREAD notifications
        # Note: delete_all_read only deletes NEEDREAD type notifications
        initial_done_count = Notification.objects.filter(
            receiver=self.user1,
            typename=Notification.Type.NEEDREAD,
            status=Notification.Status.DONE
        ).count()
        self.assertGreater(initial_done_count, 0)
        
        url = reverse('api:notification:notification-delete-all-read')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['count'], initial_done_count)
        self.assertEqual(
            response.data["message"],
            f"已删除 {initial_done_count} 条已读通知。",
        )

    def test_statistics_endpoint(self):
        """Test the statistics endpoint."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-statistics')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        
        stats = response.data
        self.assertIn('total', stats)
        self.assertIn('unread', stats)
        self.assertIn('read', stats)
        self.assertIn('need_read', stats)
        self.assertIn('need_do', stats)
        
        # Verify counts
        self.assertEqual(stats['total'], 2)  # user1 has 2 notifications
        self.assertEqual(stats['unread'], 1)  # 1 unread
        self.assertEqual(stats['read'], 1)   # 1 read
        self.assertEqual(stats['need_read'], 1)  # 1 NEEDREAD type
        self.assertEqual(stats['need_do'], 1)   # 1 NEEDDO type

    def test_notification_serializer_fields(self):
        """Test that serializer returns all required fields."""
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-detail', kwargs={'pk': self.notification1.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        data = response.data
        
        # Check all required fields are present
        required_fields = [
            'id', 'sender', 'sender_name', 'status', 'status_display',
            'title', 'title_display', 'content', 'start_time', 'typename',
            'typename_display', 'URL', 'anonymous_flag'
        ]
        
        for field in required_fields:
            self.assertIn(field, data, f"Field '{field}' missing in response")

    def test_anonymous_notification(self):
        """Test that anonymous notifications display correctly."""
        anon_notification = Notification.objects.create(
            receiver=self.user1,
            sender=self.user2,
            typename=Notification.Type.NEEDREAD,
            title="Anonymous Test",
            content="This is anonymous",
            status=Notification.Status.UNDONE,
            anonymous_flag=True
        )
        
        self.client.force_authenticate(user=self.user1)
        url = reverse('api:notification:notification-detail', kwargs={'pk': anon_notification.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['anonymous_flag'])
