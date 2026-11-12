from datetime import datetime, time, timedelta
from importlib import import_module
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from Appointment.models import Appoint, EntranceGuard, Participant, Room, User
from generic.models import PermissionBlacklist


class FinishAppointAccessTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 测试只模拟硬件边界，不加载海康原生库或连接真实门禁。
        with patch('ctypes.cdll.LoadLibrary'):
            cls.status_control = import_module('Appointment.appoint.status_control')

    def setUp(self):
        self.room = Room.objects.create(
            Rid='T101', Rtitle='测试会议室',
            Rstart=time(8), Rfinish=time(23), allow_free_access=True,
        )
        self.guards = [
            EntranceGuard.objects.create(
                door_id=index, ip=f'127.0.0.{index}',
                username='test', password='test', room=self.room,
            )
            for index in (1, 2)
        ]
        self.teacher = self.create_participant('teacher', 'teacher-id')
        self.student = self.create_participant('student', 'student-id')
        self.permission = Permission.objects.get(
            content_type__app_label='Appointment',
            content_type__model='room', codename='can_access_rooms_freely',
        )
        self.teacher.Sid.user_permissions.add(self.permission)
        self.appoint = self.create_appoint(self.teacher, self.student)
        self.sdk = self.enterContext(patch.object(self.status_control, 'HaikangSDK'))
        self.device = self.sdk.get_entrace_guard_device.return_value.__enter__.return_value
        self.enterContext(patch.object(self.status_control, 'logger'))

    def create_participant(self, username, cross_sys_uid):
        user = User.objects.create_user(username=username, name=username)
        return Participant.objects.create(Sid=user, cross_sys_uid=cross_sys_uid)

    def create_appoint(self, *participants, finish=None):
        appoint = Appoint.objects.create(
            Room=self.room, Astart=datetime.now() - timedelta(hours=1),
            Afinish=finish or datetime.now(), Aneed_num=1,
            Astatus=Appoint.Status.PROCESSING,
        )
        appoint.students.add(*participants)
        return appoint

    def finish_and_assert_revoked(self, expected):
        self.status_control.finish_appoint(self.appoint.pk)
        self.appoint.refresh_from_db()
        self.assertEqual(self.appoint.Astatus, Appoint.Status.CONFIRMED)
        if expected:
            self.assertEqual(self.device.revoke_access.call_count, len(self.guards))
            for call in self.device.revoke_access.call_args_list:
                self.assertEqual(call.args, (expected,))
        else:
            self.sdk.get_entrace_guard_device.assert_not_called()

    def test_enabled_room_preserves_teacher_and_revokes_student(self):
        self.finish_and_assert_revoked({'student-id'})

    def test_disabled_room_revokes_everyone(self):
        self.room.allow_free_access = False
        self.room.save()
        self.finish_and_assert_revoked({'teacher-id', 'student-id'})

    def test_enabled_room_without_permission_revokes_everyone(self):
        self.teacher.Sid.user_permissions.clear()
        self.finish_and_assert_revoked({'teacher-id', 'student-id'})

    def test_group_permission_preserves_teacher(self):
        self.teacher.Sid.user_permissions.clear()
        group = Group.objects.create(name='常驻教师')
        group.permissions.add(self.permission)
        self.teacher.Sid.groups.add(group)
        self.finish_and_assert_revoked({'student-id'})

    def test_blacklisted_permission_does_not_preserve_teacher(self):
        PermissionBlacklist.objects.create(user=self.teacher.Sid, permission=self.permission)
        self.finish_and_assert_revoked({'teacher-id', 'student-id'})

    def test_all_permanent_participants_finish_without_device_calls(self):
        self.student.Sid.user_permissions.add(self.permission)
        self.finish_and_assert_revoked(set())

    def test_overlapping_appointment_still_preserves_student(self):
        self.create_appoint(
            self.student, finish=self.appoint.Afinish + timedelta(hours=1))
        self.finish_and_assert_revoked(set())

    def test_revoke_failure_keeps_appointment_processing(self):
        self.device.revoke_access.side_effect = self.status_control.HaikangAPIError('test')
        self.status_control.finish_appoint(self.appoint.pk)
        self.appoint.refresh_from_db()
        self.assertEqual(self.appoint.Astatus, Appoint.Status.PROCESSING)

    def test_room_disallows_free_access_by_default(self):
        self.assertFalse(Room().allow_free_access)
