from contextlib import ExitStack
from datetime import datetime, timedelta, time, date
from unittest.mock import patch
from urllib.parse import unquote

from django.test import Client, TestCase
from django.urls import reverse

from app.models import NaturalPerson, Organization, OrganizationType
from Appointment.models import Appoint, LongTermAppoint, Participant, Room, User
from Appointment.utils.web_func import get_hour_time
from Appointment.views import _add_appoint


def _frozen_datetime(frozen_now: datetime):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now

        @classmethod
        def today(cls):
            return frozen_now.replace(
                hour=0, minute=0, second=0, microsecond=0,
            )

    return FrozenDateTime


def _freeze_now(when: datetime):
    frozen = _frozen_datetime(when)
    stack = ExitStack()
    stack.enter_context(patch('Appointment.views.datetime', frozen))
    stack.enter_context(patch('Appointment.utils.web_func.datetime', frozen))
    stack.enter_context(patch('Appointment.appoint.manage.datetime', frozen))
    return stack


def _person(username: str, name: str, *, grant_underground: bool = True):
    user = User.objects.create_user(
        username,
        name,
        User.Type.STUDENT,
        password='test',
        is_newuser=False,
    )
    person = NaturalPerson.objects.create(
        user,
        name=name,
        identity=NaturalPerson.Identity.STUDENT,
        status=NaturalPerson.GraduateStatus.UNDERGRADUATED,
    )
    if grant_underground:
        person.grant_permission('underground_appointment')
    else:
        person.revoke_permission('underground_appointment')
    return user, person


class CheckoutSidIdorTest(TestCase):
    """V19：POST /underground/check_out 不得信任客户端 Sid/Sname。"""

    def setUp(self):
        self.attacker_user, _ = _person('S100001', '攻击者甲')
        self.victim_user, _ = _person('S100002', '受害者乙')
        self.attacker = Participant.objects.create(Sid=self.attacker_user)
        self.victim = Participant.objects.create(Sid=self.victim_user)
        self.room = Room.objects.create(
            Rid='B104T',
            Rtitle='B104 研讨/活动室',
            Rmin=0,
            Rmax=10,
            Rstart=time(8, 0),
            Rfinish=time(22, 0),
            Rstatus=Room.Status.PERMITTED,
        )
        start = datetime.now().replace(
            hour=20, minute=0, second=0, microsecond=0,
        ) + timedelta(days=2)
        self.startid = (start.hour - self.room.Rstart.hour) * 2
        starttime, _ = get_hour_time(self.room, self.startid)
        endtime, _ = get_hour_time(self.room, self.startid + 1)
        self.checkout_url = reverse('Appointment:checkout_appoint')
        self.slot_query = {
            'Rid': self.room.Rid,
            'weekday': start.strftime('%a'),
            'startid': str(self.startid),
            'endid': str(self.startid),
        }
        self.slot = {
            **self.slot_query,
            'year': str(start.year),
            'month': str(start.month),
            'day': str(start.day),
            'starttime': starttime,
            'endtime': endtime,
        }
        self.base_form = {
            **self.slot,
            'non_yp_num': '0',
            'Ausage': 'V19 测试',
            'announcement': '',
        }
        patchers = [
            patch(
                'Appointment.appoint.manage.set_scheduler',
                return_value=True,
            ),
            patch(
                'Appointment.appoint.manage.set_appoint_reminder',
                return_value=True,
            ),
            patch(
                'Appointment.appoint.manage.notify_appoint',
                return_value=True,
            ),
            patch('Appointment.appoint.manage.unlock_achievement'),
            patch('Appointment.views._notify_longterm_review'),
        ]
        self.mocks = [p.start() for p in patchers]
        self.addCleanup(lambda: [p.stop() for p in patchers])
        self.notify_mock = self.mocks[2]

    def _post(self, extra=None, client=None, **overrides):
        data = dict(self.base_form)
        if extra:
            data.update(extra)
        data.update(overrides)
        http = client if client is not None else self.client
        return http.post(self.checkout_url, data=data)

    def _assert_success_redirect(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertIn('成功', unquote(response.url))

    def _assert_only_attacker_appoint(self):
        self.assertEqual(
            Appoint.objects.filter(major_student=self.victim).count(), 0,
        )
        appoint = Appoint.objects.get()
        self.assertEqual(appoint.major_student_id, self.attacker.pk)
        students = list(appoint.students.all())
        self.assertIn(self.attacker, students)
        self.assertNotIn(self.victim, students)
        return appoint

    def test_own_sid_creates_for_current_user(self):
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.attacker.get_id(), Sname=self.attacker.name,
        )
        self._assert_success_redirect(response)
        appoint = self._assert_only_attacker_appoint()
        self.notify_mock.assert_called()
        notified = self.notify_mock.call_args[0][0]
        self.assertEqual(notified.pk, appoint.pk)
        self.assertEqual(notified.major_student_id, self.attacker.pk)

    def test_post_other_sid_cannot_create_for_victim(self):
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self._assert_success_redirect(response)
        appoint = self._assert_only_attacker_appoint()
        notified = self.notify_mock.call_args[0][0]
        self.assertEqual(notified.major_student_id, self.attacker.pk)
        self.assertNotEqual(notified.major_student_id, self.victim.pk)
        self.assertEqual(appoint.pk, notified.pk)

    def test_missing_empty_or_unknown_sid_stays_current_user(self):
        self.client.force_login(self.attacker_user)
        cases = [
            {},
            {'Sid': '', 'Sname': self.victim.name},
            {'Sid': 'S999999', 'Sname': '不存在'},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                Appoint.objects.all().delete()
                self.notify_mock.reset_mock()
                response = self._post(extra)
                self._assert_success_redirect(response)
                self._assert_only_attacker_appoint()

    def test_sname_swap_does_not_change_initiator(self):
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.attacker.get_id(), Sname=self.victim.name,
        )
        self._assert_success_redirect(response)
        self._assert_only_attacker_appoint()

    def test_add_appoint_defensively_removes_identity_fields(self):
        contents = {
            'Rid': self.room.Rid,
            'students': [self.attacker.get_id()],
            'Ausage': 'V19 helper 测试',
            'announcement': '',
            'Sid': self.victim.get_id(),
            'Sname': self.victim.name,
        }

        def assert_sanitized(value):
            self.assertNotIn('Sid', value)
            self.assertNotIn('Sname', value)

        start = datetime.now() + timedelta(days=2)
        finish = start + timedelta(minutes=30)
        with (
            patch('Appointment.views._get_content_room') as get_room,
            patch('Appointment.views._get_content_students') as get_students,
            patch('Appointment.views.create_appoint') as create,
        ):
            get_room.side_effect = lambda value: (
                assert_sanitized(value) or self.room
            )
            get_students.side_effect = lambda value: (
                assert_sanitized(value) or [self.attacker]
            )
            create.return_value = (None, 'mocked')
            _add_appoint(
                contents, start, finish, non_yp_num=0,
                applicant=self.attacker,
            )

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['appointer'], self.attacker)
        self.assertEqual(contents['Sid'], self.victim.get_id())
        self.assertEqual(contents['Sname'], self.victim.name)

    def test_get_does_not_create_appointment(self):
        self.client.force_login(self.attacker_user)
        response = self.client.get(self.checkout_url, self.slot_query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Appoint.objects.count(), 0)
        body = response.content.decode()
        self.assertNotIn('name="Sid"', body)
        self.assertNotIn("name='Sid'", body)
        self.assertNotIn('name="Sname"', body)

    def test_unauthenticated_post_creates_nothing(self):
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/'))
        self.assertEqual(Appoint.objects.count(), 0)

    def test_no_underground_permission_creates_nothing(self):
        blocked_user, _ = _person(
            'S100003', '无权限丙', grant_underground=False,
        )
        Participant.objects.create(Sid=blocked_user)
        self.client.force_login(blocked_user)
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Appoint.objects.count(), 0)

    def test_invalid_account_creates_nothing(self):
        for invalid_type in (User.Type.SPECIAL, User.Type.UNAUTHORIZED):
            with self.subTest(invalid_type=invalid_type):
                self.attacker_user.utype = invalid_type
                self.attacker_user.save(update_fields=['utype'])
                self.client.force_login(self.attacker_user)
                response = self._post(
                    Sid=self.victim.get_id(), Sname=self.victim.name,
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(Appoint.objects.count(), 0)
                for side_effect_mock in self.mocks:
                    side_effect_mock.assert_not_called()

    def test_csrf_rejected_without_or_with_bad_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.attacker_user)
        get_response = csrf_client.get(self.checkout_url, self.slot_query)
        self.assertEqual(get_response.status_code, 200)
        missing = csrf_client.post(self.checkout_url, self.base_form)
        self.assertEqual(missing.status_code, 403)
        bad = csrf_client.post(
            self.checkout_url,
            {**self.base_form, 'csrfmiddlewaretoken': 'invalid'},
        )
        self.assertEqual(bad.status_code, 403)
        self.assertEqual(Appoint.objects.count(), 0)

    def test_csrf_valid_token_still_binds_session_user(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.attacker_user)
        get_response = csrf_client.get(self.checkout_url, self.slot_query)
        self.assertEqual(get_response.status_code, 200)
        token = csrf_client.cookies['csrftoken'].value
        response = csrf_client.post(self.checkout_url, {
            **self.base_form,
            'Sid': self.victim.get_id(),
            'Sname': self.victim.name,
            'csrfmiddlewaretoken': token,
        })
        self._assert_success_redirect(response)
        self._assert_only_attacker_appoint()

    def test_longterm_initiator_stays_session_user(self):
        self.attacker.longterm = True
        self.attacker.save(update_fields=['longterm'])
        self.client.force_login(self.attacker_user)
        response = self._post(
            Sid=self.victim.get_id(),
            Sname=self.victim.name,
            longterm='on',
            times='1',
            interval='1',
            start_week='0',
        )
        self._assert_success_redirect(response)
        appoint = self._assert_only_attacker_appoint()
        longterm = LongTermAppoint.objects.get()
        self.assertEqual(longterm.applicant_id, self.attacker.pk)
        self.assertEqual(longterm.appoint_id, appoint.pk)

    def test_org_account_cannot_impersonate_person(self):
        incharge = NaturalPerson.objects.get(person_id=self.attacker_user)
        otype = OrganizationType.objects.create(
            otype_id=9001,
            otype_name='测试类型',
            incharge=incharge,
            job_name_list=['负责人', '成员'],
        )
        org_user = User.objects.create_user(
            'org_a', '组织甲', User.Type.ORG,
            password='test', is_newuser=False,
        )
        Organization.objects.create(
            organization_id=org_user, oname='组织甲', otype=otype,
        )
        org_part = Participant.objects.create(Sid=org_user)
        self.client.force_login(org_user)
        response = self._post(
            Sid=self.victim.get_id(), Sname=self.victim.name,
        )
        self._assert_success_redirect(response)
        self.assertEqual(
            Appoint.objects.filter(major_student=self.victim).count(), 0,
        )
        appoint = Appoint.objects.get()
        self.assertEqual(appoint.major_student_id, org_part.pk)

    def test_stale_same_day_after_midnight_is_rejected(self):
        """跨午夜不得把表单 weekday 重映射到下一周。"""
        monday = date(2026, 8, 17)
        self.assertEqual(monday.strftime('%a'), 'Mon')
        after_midnight = datetime(2026, 8, 18, 0, 15)
        next_monday = datetime(2026, 8, 24, 20, 0)
        self.client.force_login(self.attacker_user)
        with _freeze_now(after_midnight):
            response = self._post(
                weekday='Mon',
                year=str(monday.year),
                month=str(monday.month),
                day=str(monday.day),
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn('过期', unquote(response.url))
        self.assertEqual(Appoint.objects.count(), 0)
        self.assertFalse(
            Appoint.objects.filter(Astart=next_monday).exists(),
        )

    def test_far_future_same_weekday_is_rejected(self):
        self.client.force_login(self.attacker_user)
        now = datetime(2026, 8, 18, 10, 0)
        far_monday = date(2026, 9, 14)
        self.assertEqual(far_monday.strftime('%a'), 'Mon')
        with _freeze_now(now):
            response = self._post(
                weekday='Mon',
                year=str(far_monday.year),
                month=str(far_monday.month),
                day=str(far_monday.day),
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn('过期', unquote(response.url))
        self.assertEqual(Appoint.objects.count(), 0)

    def test_weekday_date_mismatch_is_rejected(self):
        self.client.force_login(self.attacker_user)
        now = datetime(2026, 8, 18, 10, 0)
        wednesday = date(2026, 8, 19)
        self.assertEqual(wednesday.strftime('%a'), 'Wed')
        with _freeze_now(now):
            response = self._post(
                weekday='Mon',
                year=str(wednesday.year),
                month=str(wednesday.month),
                day=str(wednesday.day),
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn('不一致', unquote(response.url))
        self.assertEqual(Appoint.objects.count(), 0)

    def test_missing_absolute_date_is_rejected(self):
        self.client.force_login(self.attacker_user)
        data = dict(self.base_form)
        data.pop('year')
        response = self.client.post(self.checkout_url, data=data)
        self.assertEqual(response.status_code, 302)
        self.assertIn('无效', unquote(response.url))
        self.assertEqual(Appoint.objects.count(), 0)

    def test_in_window_absolute_date_still_succeeds(self):
        self.client.force_login(self.attacker_user)
        now = datetime(2026, 8, 18, 10, 0)
        slot_day = date(2026, 8, 20)
        with _freeze_now(now):
            response = self._post(
                weekday=slot_day.strftime('%a'),
                year=str(slot_day.year),
                month=str(slot_day.month),
                day=str(slot_day.day),
            )
            self._assert_success_redirect(response)
            appoint = Appoint.objects.get()
        self.assertEqual(appoint.Astart.date(), slot_day)
